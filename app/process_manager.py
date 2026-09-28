from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import threading
import uuid
from urllib.parse import quote
from datetime import datetime
from pathlib import Path
from typing import Any

from app.history_manager import add_history
from app.keyframe_fix import (
    build_frame_probe_command,
    build_keyframe_trim_command,
    find_first_decoded_keyframe,
    needs_keyframe_trim,
)
from app.models import DownloadRequest, HistoryEntry
from app.path_utils import LOGS_DIR, display_path, ensure_project_dirs
from app.text_utils import decode_process_output
from app.ytdlp_service import build_download_command, find_result_file_from_logs, quote_command


class DownloadStopped(Exception):
    pass


class ProcessManager:
    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None
        self.current_job_id = ""
        self.current_request: DownloadRequest | None = None
        self.log_lines: list[str] = []
        self.command = ""
        self.status = "idle"
        self.result: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._stop_requested = False
        self._event_queue: asyncio.Queue[dict[str, Any]] | None = None

    def set_event_queue(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._event_queue = queue

    def emit(self, kind: str, message: str, **payload: Any) -> None:
        event = {"type": kind, "message": message, "datetime": datetime.now().isoformat(timespec="seconds"), **payload}
        if kind == "log":
            with self._lock:
                self.log_lines.append(f"[{event['datetime']}] {message}")
                self.log_lines = self.log_lines[-2000:]
        queue = self._event_queue
        if queue is not None:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def get_logs(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self.status,
                "job_id": self.current_job_id,
                "command": self.command,
                "logs": list(self.log_lines),
                "result": dict(self.result),
                "running": self.process is not None and self.process.poll() is None,
            }

    def clear_logs(self) -> None:
        with self._lock:
            self.log_lines.clear()
            self.command = ""
        self.emit("status", "Логи очищены")

    def start_download(self, request: DownloadRequest) -> str:
        if self.process is not None and self.process.poll() is None:
            raise ValueError("Уже выполняется загрузка")
        command_args = build_download_command(request)
        self.current_job_id = str(uuid.uuid4())
        self.current_request = request
        self.command = quote_command(command_args)
        self.status = "running"
        self.result = {}
        self._stop_requested = False
        self.emit("log", f"Итоговая команда: {self.command}")
        thread = threading.Thread(target=self._run_download, args=(command_args, request, self.current_job_id), daemon=True)
        thread.start()
        return self.current_job_id

    def _run_download(self, command_args: list[str], request: DownloadRequest, job_id: str) -> None:
        ensure_project_dirs()
        captured_output: list[str] = []
        log_path = LOGS_DIR / f"{job_id}.log"
        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            self.process = subprocess.Popen(
                command_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                shell=False,
                creationflags=creationflags,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                text = decode_process_output(line).rstrip("\r\n")
                captured_output.append(text)
                self.emit("log", text)
            return_code = self.process.wait()
            log_path.write_text("\n".join(captured_output), encoding="utf-8")
            if self._stop_requested:
                self.status = "stopped"
                self.emit("log", "Процесс остановлен пользователем")
                self._write_history(request, "stopped", "", "Процесс остановлен пользователем")
            elif return_code == 0:
                output_file = find_result_file_from_logs(captured_output)
                if request.section_enabled and request.section_keyframe_fix and output_file:
                    self._fix_section_start(Path(output_file))
                self.status = "success"
                self.result = self._build_result(output_file, request, "Готово")
                self.emit("result", "Загрузка завершена", result=self.result)
                self._write_history(request, "success", output_file, "")
            else:
                self.status = "error"
                error = f"yt-dlp завершился с кодом {return_code}"
                self.emit("log", error)
                self._write_history(request, "error", "", error)
        except DownloadStopped:
            self.status = "stopped"
            self.emit("log", "Обработка остановлена пользователем")
            self._write_history(request, "stopped", "", "Обработка остановлена пользователем")
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            self.status = "error"
            self.emit("log", f"Ошибка backend: {exc}")
            self._write_history(request, "error", "", str(exc))
        finally:
            self.process = None
            self.emit("status", self.status)

    def _run_postprocess_command(self, command: list[str], emit_output: bool = True) -> tuple[int, bytes]:
        self.emit("log", f"Команда обработки: {quote_command(command)}")
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0  # type: ignore[attr-defined]
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            creationflags=creationflags,
        )
        output = bytearray()
        assert self.process.stdout is not None
        for line in self.process.stdout:
            output.extend(line)
            if emit_output:
                self.emit("log", decode_process_output(line).rstrip("\r\n"))
        return self.process.wait(), bytes(output)

    def _fix_section_start(self, output_file: Path) -> None:
        if not output_file.exists():
            raise RuntimeError(f"Не найден скачанный файл для проверки ключевого кадра: {output_file}")
        self.emit("log", "Проверяю начало фрагмента по фактически декодированным кадрам ffprobe...")
        return_code, raw_probe = self._run_postprocess_command(build_frame_probe_command(output_file), emit_output=False)
        if self._stop_requested:
            raise DownloadStopped
        if return_code != 0:
            raise RuntimeError(f"ffprobe завершился с кодом {return_code}")
        timestamp, packet_size = find_first_decoded_keyframe(decode_process_output(raw_probe))
        if timestamp is None:
            self.emit("log", "Видеопоток или декодированный I-кадр не найден; файл оставлен без изменений")
            return
        if not needs_keyframe_trim(timestamp):
            self.emit("log", f"Ключевой кадр уже в начале (размер пакета {packet_size} байт)")
            return
        self.emit(
            "log",
            f"Первый реальный I-кадр найден на {timestamp:.6f} с "
            f"(размер пакета: {packet_size} байт); обрезаю без перекодирования",
        )
        command, temporary = build_keyframe_trim_command(output_file, timestamp)
        temporary.unlink(missing_ok=True)
        return_code, _ = self._run_postprocess_command(command)
        if self._stop_requested:
            temporary.unlink(missing_ok=True)
            raise DownloadStopped
        if return_code != 0 or not temporary.exists() or temporary.stat().st_size == 0:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg не смог обрезать файл без перекодирования (код {return_code})")
        temporary.replace(output_file)
        self.emit("log", "Исходный файл заменён версией, начинающейся с ключевого кадра")

    def _build_result(self, output_file: str, request: DownloadRequest, status: str) -> dict[str, Any]:
        path = Path(output_file) if output_file else None
        size = path.stat().st_size if path and path.exists() else 0
        suffix = path.suffix.lower() if path else ""
        preview_type = ""
        if suffix in {".mp4", ".webm", ".ogg", ".mov", ".m4v"}:
            preview_type = "video"
        elif suffix in {".mp3", ".m4a", ".opus", ".wav", ".oga"}:
            preview_type = "audio"
        return {
            "file": output_file,
            "folder": str(path.parent) if path else request.download_dir,
            "size": size,
            "status": status,
            "preview_type": preview_type,
            "preview_url": f"/api/media?path={quote(output_file)}" if output_file else "",
        }

    def _write_history(self, request: DownloadRequest, status: str, output_file: str, error: str) -> None:
        fmt = request.selected_format if request.download_mode == "manual" else request.download_mode
        entry = HistoryEntry(
            id=str(uuid.uuid4()),
            datetime=datetime.now().isoformat(timespec="seconds"),
            url=request.url,
            title=Path(output_file).stem if output_file else "",
            download_dir=request.download_dir,
            output_file=output_file,
            mode=request.download_mode,
            format=fmt,
            status=status,
            error=error,
        )
        add_history(entry)

    def stop(self) -> bool:
        if self.process is None or self.process.poll() is not None:
            return False
        self._stop_requested = True
        self.emit("log", "Запрошена остановка процесса")
        if os.name == "nt":
            try:
                self.process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            except Exception:
                self.process.terminate()
        else:
            self.process.terminate()
        return True
