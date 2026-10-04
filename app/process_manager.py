from __future__ import annotations

import asyncio
import os
import re
import signal
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.history_manager import add_history
from app.keyframe_fix import build_frame_probe_command, build_keyframe_trim_command, find_first_decoded_keyframe, needs_keyframe_trim
from app.models import DownloadRequest, HistoryEntry
from app.path_utils import LOGS_DIR, ensure_project_dirs
from app.text_utils import decode_process_output
from app.ytdlp_service import build_download_command, find_result_file_from_logs, quality_key, quote_command

PROGRESS_RE = re.compile(r"\[download\]\s+(?P<percent>[\d.]+)%\s+of\s+(?P<size>.+?)(?:\s+in\s+(?P<elapsed>\S+))?(?:\s+at\s+(?P<speed>\S+))?\s*$")


class DownloadStopped(Exception):
    pass


@dataclass
class DownloadJob:
    id: str
    request: DownloadRequest
    command: str
    process: subprocess.Popen[bytes] | None = None
    status: str = "running"
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    progress: float = 0.0
    progress_text: str = "Ожидание данных yt-dlp"
    stop_requested: bool = False
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def public(self) -> dict[str, Any]:
        running = self.process is not None and self.process.poll() is None
        return {"id": self.id, "status": self.status, "command": self.command, "logs": list(self.logs),
                "result": dict(self.result), "progress": self.progress, "progress_text": self.progress_text,
                "running": running or (self.status == "running" and self.process is None), "url": self.request.url,
                "filename": self.request.filename_template, "started_at": self.started_at}


class ProcessManager:
    """Owns independent yt-dlp processes so downloads can run concurrently."""

    def __init__(self) -> None:
        self.jobs: dict[str, DownloadJob] = {}
        self.log_lines: list[str] = []
        self._lock = threading.RLock()
        self._event_queue: asyncio.Queue[dict[str, Any]] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_queue(self, queue: asyncio.Queue[dict[str, Any]], loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._event_queue, self._loop = queue, loop

    def emit(self, kind: str, message: str, job_id: str = "", **payload: Any) -> None:
        event = {"type": kind, "message": message, "datetime": datetime.now().isoformat(timespec="seconds"), "job_id": job_id, **payload}
        if kind == "log":
            line = f"[{event['datetime']}]" + (f" [{job_id[:8]}]" if job_id else "") + f" {message}"
            with self._lock:
                self.log_lines = (self.log_lines + [line])[-4000:]
                if job_id in self.jobs:
                    self.jobs[job_id].logs = (self.jobs[job_id].logs + [line])[-2000:]
        if self._event_queue is not None:
            put = lambda: self._event_queue.put_nowait(event) if not self._event_queue.full() else None
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(put)

    def get_logs(self) -> dict[str, Any]:
        with self._lock:
            jobs = sorted((job.public() for job in self.jobs.values()), key=lambda item: item["started_at"], reverse=True)
            running = sum(1 for job in jobs if job["running"])
            completed = sum(1 for job in jobs if job["status"] == "success")
            return {"status": "running" if running else "idle", "logs": list(self.log_lines), "jobs": jobs,
                    "running": running > 0, "running_count": running, "completed_count": completed, "total_count": len(jobs)}

    def clear_logs(self) -> None:
        with self._lock:
            self.log_lines.clear()
            for job in self.jobs.values():
                job.logs.clear()
        self.emit("status", "Логи очищены")

    def start_download(self, request: DownloadRequest) -> str:
        args = build_download_command(request)
        job = DownloadJob(str(uuid.uuid4()), request, quote_command(args))
        with self._lock:
            self.jobs[job.id] = job
        self.emit("log", f"Итоговая команда: {job.command}", job.id)
        threading.Thread(target=self._run_download, args=(job, args), daemon=True).start()
        return job.id

    def _update_progress(self, job: DownloadJob, text: str) -> None:
        match = PROGRESS_RE.search(text)
        if not match:
            return
        job.progress = min(100.0, float(match.group("percent")))
        details = [f"{job.progress:g}%", f"из {match.group('size').strip()}"]
        if match.group("elapsed"): details.append(f"за {match.group('elapsed')}")
        if match.group("speed"): details.append(f"на {match.group('speed')}")
        job.progress_text = " ".join(details)
        self.emit("progress", job.progress_text, job.id, progress=job.progress)

    def _run_download(self, job: DownloadJob, args: list[str]) -> None:
        ensure_project_dirs(); captured: list[str] = []
        try:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0  # type: ignore[attr-defined]
            job.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0, shell=False, creationflags=flags)
            assert job.process.stdout is not None
            for raw in job.process.stdout:
                text = decode_process_output(raw).rstrip("\r\n")
                captured.append(text); self._update_progress(job, text); self.emit("log", text, job.id)
            code = job.process.wait()
            (LOGS_DIR / f"{job.id}.log").write_text("\n".join(captured), encoding="utf-8")
            if job.stop_requested:
                job.status = "stopped"; job.progress_text = "Остановлено"; self._write_history(job, "stopped", "", "Остановлено пользователем")
            elif code == 0:
                output = find_result_file_from_logs(captured)
                if job.request.section_enabled and job.request.section_keyframe_fix and output:
                    self._fix_section_start(job, Path(output))
                job.status = "success"; job.progress = 100; job.progress_text = "Завершено"
                job.result = self._build_result(output, job.request, "Готово")
                self.emit("result", "Загрузка завершена", job.id, result=job.result)
                self._write_history(job, "success", output, "")
            else:
                job.status = "error"; job.progress_text = f"Ошибка (код {code})"
                self._write_history(job, "error", "", job.progress_text)
        except DownloadStopped:
            job.status = "stopped"; job.progress_text = "Остановлено"; self._write_history(job, "stopped", "", "Остановлено пользователем")
        except Exception as exc:
            job.status = "error"; job.progress_text = f"Ошибка: {exc}"; self.emit("log", job.progress_text, job.id)
            self._write_history(job, "error", "", str(exc))
        finally:
            job.process = None; self.emit("status", job.status, job.id)

    def _run_command(self, job: DownloadJob, command: list[str], emit_output: bool = True) -> tuple[int, bytes]:
        self.emit("log", f"Команда обработки: {quote_command(command)}", job.id)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0  # type: ignore[attr-defined]
        job.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False, creationflags=flags)
        output = bytearray(); assert job.process.stdout is not None
        for line in job.process.stdout:
            output.extend(line)
            if emit_output: self.emit("log", decode_process_output(line).rstrip("\r\n"), job.id)
        return job.process.wait(), bytes(output)

    def _fix_section_start(self, job: DownloadJob, output_file: Path) -> None:
        if not output_file.exists(): raise RuntimeError(f"Не найден скачанный файл: {output_file}")
        code, raw = self._run_command(job, build_frame_probe_command(output_file), False)
        if job.stop_requested: raise DownloadStopped
        if code: raise RuntimeError(f"ffprobe завершился с кодом {code}")
        timestamp, _ = find_first_decoded_keyframe(decode_process_output(raw))
        if timestamp is None or not needs_keyframe_trim(timestamp): return
        command, temporary = build_keyframe_trim_command(output_file, timestamp); temporary.unlink(missing_ok=True)
        code, _ = self._run_command(job, command)
        if job.stop_requested: temporary.unlink(missing_ok=True); raise DownloadStopped
        if code or not temporary.exists(): raise RuntimeError(f"ffmpeg завершился с кодом {code}")
        temporary.replace(output_file)

    @staticmethod
    def _build_result(output_file: str, request: DownloadRequest, status: str) -> dict[str, Any]:
        path = Path(output_file) if output_file else None; size = path.stat().st_size if path and path.exists() else 0
        suffix = path.suffix.lower() if path else ""; preview = "video" if suffix in {".mp4", ".webm", ".ogg", ".mov", ".m4v"} else "audio" if suffix in {".mp3", ".m4a", ".opus", ".wav", ".oga"} else ""
        return {"file": output_file, "folder": str(path.parent) if path else request.download_dir, "size": size, "status": status,
                "preview_type": preview, "preview_url": f"/api/media?path={quote(output_file)}" if output_file else ""}

    def _write_history(self, job: DownloadJob, status: str, output_file: str, error: str) -> None:
        request = job.request
        add_history(HistoryEntry(id=str(uuid.uuid4()), datetime=datetime.now().isoformat(timespec="seconds"), url=request.url,
            title=Path(output_file).stem if output_file else request.filename_template, download_dir=request.download_dir,
            output_file=output_file, mode=request.download_mode, format=request.selected_format if request.download_mode == "manual" else request.download_mode,
            status=status, error=error, filename_template=request.filename_template, quality_key=quality_key(request)))

    def stop(self, job_id: str = "") -> bool:
        with self._lock:
            targets = [self.jobs[job_id]] if job_id and job_id in self.jobs else list(self.jobs.values()) if not job_id else []
        stopped = False
        for job in targets:
            if job.process is None or job.process.poll() is not None: continue
            job.stop_requested = True; stopped = True; self.emit("log", "Запрошена остановка процесса", job.id)
            try:
                job.process.send_signal(signal.CTRL_BREAK_EVENT) if os.name == "nt" else job.process.terminate()  # type: ignore[attr-defined]
            except Exception: job.process.terminate()
        return stopped
