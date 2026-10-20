from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import threading
import time
import uuid
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from app.history_manager import add_history
from app.keyframe_fix import build_frame_probe_command, build_keyframe_trim_command, find_first_decoded_keyframe, needs_keyframe_trim
from app.json_store import atomic_write, read
from app.models import DownloadRequest, HistoryEntry
from app.path_utils import JOBS_PATH, LOGS_DIR, build_output_template, ensure_project_dirs, ensure_writable_directory, windows_path_key
from app.recovery import Failure, classify_failure, retry_delay
from app.text_utils import decode_process_output
from app.ytdlp_service import build_download_command, compatible_requests, explicit_format, suggest_non_conflicting_filename, quality_key, quote_command, redact_args

ACTIVE = {"queued", "preparing", "downloading", "retry_wait", "postprocessing"}
TERMINAL = {"stopped", "error", "success", "interrupted"}
PROGRESS_RE = re.compile(r"\[download\]\s+(?P<percent>[\d.]+)%\s+of\s+(?P<size>.+?)(?:\s+in\s+(?P<elapsed>\S+))?(?:\s+at\s+(?P<speed>\S+))?\s*$")

class DownloadConflict(ValueError):
    def __init__(self, code: str, owner_job_id: str, actions: list[str], message: str):
        super().__init__(message)
        self.detail = {"code": code, "owner_job_id": owner_job_id, "actions": actions, "message": message}


@dataclass
class DownloadJob:
    id: str
    request: DownloadRequest
    output_template: str
    status: str = "queued"
    process: subprocess.Popen[bytes] | None = None
    attempt: int = 0
    attempt_id: str = ""
    run_id: str = ""
    worker_active: bool = False
    resuming: bool = False
    resolved_format: str = ""
    return_code: int | None = None
    reason: str = ""
    next_retry_at: str = ""
    progress: float | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed: float | None = None
    eta: float | None = None
    stream: str = ""
    stage: str = "queued"
    result: dict[str, Any] = field(default_factory=dict)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    manifest: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    completed_at: str = ""
    command: str = ""
    argv: list[str] = field(default_factory=list)
    last_message_at: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    retry_now: threading.Event = field(default_factory=threading.Event, repr=False)
    diagnostic_tail: deque[str] = field(default_factory=lambda: deque(maxlen=80), repr=False)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "attempt": self.attempt, "max_restarts": self.request.max_restarts,
                "return_code": self.return_code, "reason": self.reason, "next_retry_at": self.next_retry_at,
                "progress": self.progress, "downloaded_bytes": self.downloaded_bytes, "total_bytes": self.total_bytes,
                "speed": self.speed, "eta": self.eta, "stream": self.stream, "stage": self.stage,
                "result": dict(self.result), "running": self.process is not None and self.process.poll() is None, "worker_active": self.worker_active,
                "url": self.request.url, "filename": self.request.filename_template, "started_at": self.started_at,
                "completed_at": self.completed_at, "attempts": list(self.attempts),
                "command": self.command, "argv": list(self.argv), "last_message_at": self.last_message_at,
                "access_summary": {"proxy": self.request.proxy_enabled, "cookies": self.request.cookies_enabled, "section": self.request.section_enabled}}

    def stored(self) -> dict[str, Any]:
        data = self.public(); data["request"] = self.request.model_dump(); data["output_template"] = self.output_template; data["manifest"] = self.manifest; data["resolved_format"] = self.resolved_format
        return data

class EventBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock(); self._clients: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = {}; self.revision = 0
    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.revision += 1; event = {**event, "event_id": self.revision, "revision": self.revision}
            clients = list(self._clients.items())
        for key, (loop, queue) in clients:
            def put(q=queue, k=key, item=event):
                if q.full():
                    while not q.empty():
                        try: q.get_nowait()
                        except asyncio.QueueEmpty: break
                    q.put_nowait({"type": "snapshot_required", "event_id": item["event_id"], "revision": item["revision"]})
                else: q.put_nowait(item)
            loop.call_soon_threadsafe(put)
    def subscribe(self, loop: asyncio.AbstractEventLoop) -> tuple[str, asyncio.Queue]:
        key = str(uuid.uuid4()); q: asyncio.Queue = asyncio.Queue(maxsize=100)
        with self._lock: self._clients[key] = (loop, q)
        return key, q
    def unsubscribe(self, key: str) -> None:
        with self._lock: self._clients.pop(key, None)

class ProcessManager:
    def __init__(self, popen: Callable[..., subprocess.Popen] = subprocess.Popen, wait: Callable[[threading.Event, float], bool] | None = None) -> None:
        self.jobs: dict[str, DownloadJob] = {}; self._lock = threading.RLock(); self._popen = popen
        self._wait = wait or (lambda event, seconds: event.wait(seconds)); self.broker = EventBroker(); self._reserved: dict[str, tuple[str, str]] = {}; self._partial_owners: dict[str, str] = {}
        self._slots = threading.BoundedSemaphore(2); self._load_jobs()

    def configure(self, maximum: int) -> None:
        # Applied for new process lifetime; changing live semaphore would race active jobs.
        if not any(j.worker_active or j.status in ACTIVE for j in self.jobs.values()): self._slots = threading.BoundedSemaphore(maximum)

    def emit(self, kind: str, message: str, job_id: str = "", **payload: Any) -> None:
        event = {"type": kind, "message": message, "datetime": datetime.now().isoformat(timespec="seconds"), "job_id": job_id, **payload}
        if job_id and kind == "log": self._append_log(job_id, message)
        self.broker.publish(event)

    def _append_log(self, job_id: str, message: str) -> None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with (LOGS_DIR / f"{job_id}.log").open("a", encoding="utf-8") as handle: handle.write(message + "\n")

    def _persist(self) -> None:
        with self._lock: atomic_write(JOBS_PATH, {"schema_version": 2, "jobs": [job.stored() for job in self.jobs.values()]})

    def _load_jobs(self) -> None:
        data = read(JOBS_PATH, {"schema_version": 2, "jobs": []})
        for raw in data.get("jobs", []) if isinstance(data, dict) else []:
            try:
                request = DownloadRequest(**raw["request"]); status = raw.get("status", "interrupted")
                if status in ACTIVE: status = "interrupted"
                job = DownloadJob(raw["id"], request, raw["output_template"], status=status, attempt=raw.get("attempt", 0), reason="Работа backend была прервана" if status == "interrupted" else raw.get("reason", ""), result=raw.get("result", {}), attempts=raw.get("attempts", []), manifest=raw.get("manifest", []), started_at=raw.get("started_at", ""), completed_at=raw.get("completed_at", ""), command=raw.get("command", ""), argv=raw.get("argv", []), last_message_at=raw.get("last_message_at", ""))
                job.resolved_format = raw.get("resolved_format", "")
                self.jobs[job.id] = job; self._partial_owners[windows_path_key(job.output_template)] = job.id
            except Exception: continue

    def snapshot(self) -> dict[str, Any]:
        with self._lock: jobs = sorted((j.public() for j in self.jobs.values()), key=lambda x: x["started_at"], reverse=True)
        return {"revision": self.broker.revision, "jobs": jobs, "running_count": sum(j["worker_active"] or j["status"] in ACTIVE for j in jobs)}

    def get_logs(self) -> dict[str, Any]: return self.snapshot()
    def log_tail(self, job_id: str, limit: int = 300, offset: int = 0) -> dict[str, Any]:
        path = LOGS_DIR / f"{job_id}.log"
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
        limit = max(1, min(limit, 2000)); start = max(0, offset) if offset else max(0, len(lines) - limit)
        modified = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") if path.exists() else ""
        return {"lines": lines[start:start + limit], "next_offset": min(len(lines), start + limit), "total": len(lines), "last_message_at": modified}

    def clear_logs(self) -> None:
        # Only clear the visible tails/files explicitly; job state is untouched.
        for job_id in list(self.jobs): (LOGS_DIR / f"{job_id}.log").unlink(missing_ok=True)

    def _conflict(self, key: str, request: DownloadRequest, retry_job: DownloadJob | None = None, template: str = "") -> None:
        active = self._reserved.get(key)
        if active:
            raise DownloadConflict("path_active", active[0], ["show_job"], "Путь занят активным заданием")
        owner_id = self._partial_owners.get(key)
        owner = self.jobs.get(owner_id or "")
        if retry_job is not None:
            if owner and owner.id != retry_job.id:
                raise DownloadConflict("partial_incompatible", owner.id, ["rename"], "Артефакты пути уже принадлежат другому заданию; выберите новое имя")
            output = self._existing_output(retry_job.output_template, request)
            if output:
                suggested = suggest_non_conflicting_filename(output)
                conflict = DownloadConflict("output_exists", retry_job.id, ["rename"], "Готовый файл уже существует; выберите новое имя, чтобы сохранить его и partial")
                conflict.detail.update(path=str(output), suggested_template=suggested.stem)
                raise conflict
            if retry_job.attempt and not (retry_job.resolved_format or
                    (request.download_mode == "manual" and explicit_format(request.selected_format) and not request.extra_args.strip())):
                raise DownloadConflict("selection_unresolved", retry_job.id, ["rename"], "Фактические потоки старого задания неизвестны; безопасная докачка не подтверждена. Выберите новое имя")
        elif self._has_partial_artifacts(key, template) and (owner is None or owner.status == "success"):
            raise DownloadConflict("partial_incompatible", owner.id if owner else "", ["rename"], "Найдены старые временные файлы без совместимого незавершённого задания; выберите новое имя")
        elif owner and owner.status != "success":
            compatible = compatible_requests(owner.request, request)
            raise DownloadConflict("resume_available" if compatible else "partial_incompatible", owner.id,
                                   ["resume", "rename"] if compatible else ["rename"],
                                   "Продолжить существующее задание" if compatible else "Параметры старых partial несовместимы или выбор потоков не разрешён; выберите новое имя")

    @staticmethod
    def _existing_output(template: str, request: DownloadRequest) -> Path | None:
        path = Path(template)
        prefix = path.name.removesuffix("%(ext)s").casefold()
        if not path.parent.exists():
            return None
        extensions = {request.audio_format} if request.download_mode == "audio" else {"mp4", "m4a", "mkv", "webm", "mp3", "opus", "wav", "ogg", "mov", "avi", "flac", "aac"}
        for candidate in path.parent.iterdir():
            name = candidate.name.casefold()
            if (candidate.is_file() and name.startswith(prefix)
                    and name[len(prefix):] in extensions):
                return candidate
        return None

    def _has_partial_artifacts(self, key: str, candidate_template: str) -> bool:
        # Compare keys, but always inspect original physical paths (including legacy jobs).
        owner = self.jobs.get(self._partial_owners.get(key, ""))
        template = owner.output_template if owner else candidate_template
        if not template:
            return False
        path = Path(template)
        prefix = path.name.removesuffix("%(ext)s").casefold()
        return any(candidate.is_file() and candidate.name.casefold().startswith(prefix)
                   and (candidate.name.casefold().endswith((".part", ".ytdl"))
                        or re.match(r"f[^.]+\.", candidate.name[len(prefix):], re.IGNORECASE))
                   for candidate in path.parent.iterdir()) if path.parent.exists() else False

    def _claim(self, job: DownloadJob) -> str:
        run_id = str(uuid.uuid4())
        job.run_id = run_id; job.worker_active = True
        self._reserved[windows_path_key(job.output_template)] = (job.id, run_id)
        self._partial_owners[windows_path_key(job.output_template)] = job.id
        return run_id

    def _release(self, job: DownloadJob, run_id: str) -> None:
        with self._lock:
            key = windows_path_key(job.output_template)
            if self._reserved.get(key) == (job.id, run_id):
                del self._reserved[key]
                job.worker_active = False

    def _launch(self, job: DownloadJob) -> None:
        try:
            self._publish(job, "Добавлено в очередь")
            threading.Thread(target=self._worker, args=(job,), daemon=True).start()
        except Exception:
            self._finish(job, "error", "Не удалось запустить рабочий поток")
            self._release(job, job.run_id)
            raise

    def start_download(self, request: DownloadRequest) -> str:
        ensure_project_dirs(); directory = ensure_writable_directory(request.download_dir)
        job_id = str(uuid.uuid4())
        if not request.filename_template: request = request.model_copy(update={"filename_template": f"download-{job_id[:8]}"})
        template = build_output_template(directory, request.filename_template); key = windows_path_key(template)
        with self._lock:
            self._conflict(key, request, template=template)
            job = DownloadJob(job_id, request.model_copy(deep=True), template)
            self.jobs[job.id] = job; self._claim(job)
        self._launch(job)
        return job.id

    def _publish(self, job: DownloadJob, message: str) -> None:
        try:
            self._persist(); self.emit("job", message, job.id, job=job.public())
        except Exception:
            # State transitions must not die because diagnostics storage failed.
            self.broker.publish({"type": "job", "message": message, "job_id": job.id, "job": job.public()})

    def _worker(self, job: DownloadJob) -> None:
        run_id = job.run_id
        try:
            self._worker_body(job)
        finally:
            # The worker and every subprocess must finish before another run can write.
            if job.process is not None:
                self._terminate(job)
                job.process.wait()
                job.process = None
            self._release(job, run_id)
            self._publish(job, job.reason)

    def _worker_body(self, job: DownloadJob) -> None:
        with self._slots:
            try:
                if job.cancel_event.is_set(): return self._finish(job, "stopped", "Остановлено до запуска")
                cdn_refreshes = 0
                budget_start = job.attempt
                while True:
                    job.attempt += 1; job.attempt_id = str(uuid.uuid4()); current = job.attempt_id
                    job.status = job.stage = "preparing"; job.next_retry_at = ""; job.diagnostic_tail.clear(); self._publish(job, "Получение метаданных")
                    args = build_download_command(job.request, max(2, job.attempt) if job.resuming else job.attempt, job.output_template, job.resolved_format)
                    safe_args = self._redact_args(args); job.argv = safe_args; job.command = quote_command(safe_args)
                    self._safe_log(job, f"=== attempt {job.attempt} ({current}) ===\nargv-json: {json.dumps(safe_args, ensure_ascii=False)}\ncmd-display (не для shell): {job.command}")
                    if job.cancel_event.is_set(): return self._finish(job, "stopped", "Остановлено до запуска")
                    code, output = self._run_attempt(job, args, current)
                    if job.cancel_event.is_set(): return self._finish(job, "stopped", "Остановлено пользователем")
                    failure = classify_failure(job.stage, code, list(job.diagnostic_tail)) if code else None
                    job.attempts.append({"number": job.attempt, "attempt_id": current, "return_code": code, "reason": failure.code if failure else "success"})
                    if code == 0:
                        result_path = Path(output) if output else None
                        if not result_path or not result_path.exists() or result_path.stat().st_size <= 0:
                            failure = Failure("missing_output", "manual", "yt-dlp завершился без непустого итогового файла")
                        else:
                            job.manifest.append(str(result_path))
                            if job.request.section_enabled and job.request.section_keyframe_fix:
                                try: self._fix_section_start(job, result_path)
                                except Exception as exc:
                                    if job.cancel_event.is_set(): return self._finish(job, "stopped", "Остановлено во время постобработки")
                                    return self._finish(job, "error", f"Ошибка постобработки: {exc}")
                            return self._finish(job, "success", "Готово", str(result_path))
                    assert failure is not None
                    job.reason = failure.message; job.return_code = code
                    allowed = job.request.auto_retry and job.attempt - budget_start <= job.request.max_restarts
                    if failure.action == "refresh_once": allowed = allowed and cdn_refreshes < 1; cdn_refreshes += 1
                    elif failure.action not in {"retry", "retry_429"}: allowed = False
                    if not allowed: return self._finish(job, "error", failure.message)
                    delay = failure.retry_after or retry_delay(job.attempt)
                    job.status = job.stage = "retry_wait"; job.next_retry_at = (datetime.now() + timedelta(seconds=delay)).isoformat(timespec="seconds"); self._publish(job, failure.message)
                    job.retry_now.clear(); deadline = time.monotonic() + delay
                    while not job.cancel_event.is_set() and not job.retry_now.is_set() and time.monotonic() < deadline:
                        self._wait(job.cancel_event, min(.25, max(0, deadline - time.monotonic())))
                    if job.cancel_event.is_set(): return self._finish(job, "stopped", "Остановлено во время ожидания")
            except Exception as exc:
                reason = f"Ошибка задания: {exc}"
                self._safe_log(job, reason)
                self._finish(job, "stopped" if job.cancel_event.is_set() else "error", "Остановлено пользователем" if job.cancel_event.is_set() else reason)
            finally:
                if job.process is not None:
                    self._terminate(job)
                    job.process.wait()
                    job.process = None

    def _run_attempt(self, job: DownloadJob, args: list[str], attempt_id: str) -> tuple[int, str]:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0  # type: ignore[attr-defined]
        with self._lock:
            if job.attempt_id != attempt_id:
                return 1, ""
            try: process = self._popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0, shell=False, creationflags=flags)
            except OSError as exc: job.diagnostic_tail.append(str(exc)); return 127, ""
            job.process = process
        self._publish(job, "yt-dlp запущен; получение метаданных")
        if job.cancel_event.is_set(): self._terminate(job)
        result = ""; assert process.stdout is not None
        try:
            for raw in process.stdout:
                text = decode_process_output(raw).rstrip("\r\n"); job.diagnostic_tail.append(text); self._safe_log(job, text)
                if text.startswith("__YTM_SELECTION__"):
                    try:
                        selection = json.loads(text[len("__YTM_SELECTION__"):])
                        selected = None
                        if isinstance(selection, list) and len(selection) == 2:
                            format_id, streams = selection
                            selected = "+".join(streams) if isinstance(streams, list) and streams and all(isinstance(x, str) for x in streams) else format_id
                        if isinstance(selected, str) and explicit_format(selected):
                            job.resolved_format = selected
                            self._persist()
                    except (ValueError, TypeError): pass
                elif text.startswith("__YTM_PROGRESS__"):
                    if job.stage != "downloading": job.status = job.stage = "downloading"; self._publish(job, "Скачивание")
                    self._progress(job, text[len("__YTM_PROGRESS__"):], attempt_id)
                elif text.startswith("__YTM_RESULT__"):
                    job.status = job.stage = "postprocessing"; self._publish(job, "Завершение обработки"); result = text[len("__YTM_RESULT__"):].strip()
                elif text.startswith(("[Merger]", "[ExtractAudio]", "[VideoConvertor]", "[Fixup")) and job.stage != "postprocessing":
                    job.status = job.stage = "postprocessing"; self._publish(job, "Обработка ffmpeg")
            code = process.wait(); job.return_code = code
            return code, result
        finally:
            if process.poll() is None:
                self._terminate(job)
                process.wait()
            try: process.stdout.close()
            except OSError: pass
            with self._lock:
                if job.attempt_id == attempt_id: job.process = None

    def _safe_log(self, job: DownloadJob, message: str) -> None:
        job.last_message_at = datetime.now().isoformat(timespec="seconds")
        try: self._append_log(job.id, message)
        except OSError as exc: job.diagnostic_tail.append(f"Ошибка записи лога: {exc}")

    def _run_postprocess(self, job: DownloadJob, command: list[str], capture: bool = False) -> tuple[int, bytes]:
        if job.cancel_event.is_set(): raise RuntimeError("остановлено")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0  # type: ignore[attr-defined]
        process = self._popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False, creationflags=flags)
        job.process = process; self._publish(job, "Постобработка")
        output = bytearray(); assert process.stdout is not None
        try:
            for raw in process.stdout:
                output.extend(raw)
                if not capture: self._safe_log(job, decode_process_output(raw).rstrip("\r\n"))
            code = process.wait()
            if job.cancel_event.is_set(): raise RuntimeError("остановлено")
            return code, bytes(output)
        finally:
            if process.poll() is None:
                self._terminate(job)
                process.wait()
            try: process.stdout.close()
            except OSError: pass
            job.process = None

    def _fix_section_start(self, job: DownloadJob, output: Path) -> None:
        job.status = job.stage = "postprocessing"; self._publish(job, "Проверка ключевого кадра")
        code, raw = self._run_postprocess(job, build_frame_probe_command(output), capture=True)
        if code: raise RuntimeError(f"ffprobe завершился с кодом {code}")
        timestamp, _ = find_first_decoded_keyframe(decode_process_output(raw))
        if not needs_keyframe_trim(timestamp): return
        assert timestamp is not None
        command, temporary = build_keyframe_trim_command(output, timestamp); temporary.unlink(missing_ok=True)
        code, _ = self._run_postprocess(job, command)
        if code or not temporary.exists() or temporary.stat().st_size == 0:
            temporary.unlink(missing_ok=True); raise RuntimeError(f"ffmpeg завершился с кодом {code}")
        temporary.replace(output)

    def _progress(self, job: DownloadJob, value: str, attempt_id: str) -> None:
        if job.attempt_id != attempt_id: return
        fields = value.split("|"); number = lambda x, typ: typ(float(x)) if x not in {"", "NA", "None"} else None
        try:
            job.downloaded_bytes = number(fields[0], int); job.total_bytes = number(fields[1], int) or number(fields[2], int); job.speed = number(fields[3], float); job.eta = number(fields[4], float); job.stream = fields[5] if len(fields) > 5 else ""
            job.progress = round(job.downloaded_bytes * 100 / job.total_bytes, 2) if job.downloaded_bytes is not None and job.total_bytes else None
        except (ValueError, IndexError): return
        self.emit("job", "progress", job.id, job=job.public())

    @staticmethod
    def _redact_args(args: list[str]) -> list[str]:
        return redact_args(args)

    def _finish(self, job: DownloadJob, status: str, reason: str, output: str = "") -> None:
        job.status = job.stage = status; job.reason = reason; job.next_retry_at = ""; job.completed_at = datetime.now().isoformat(timespec="seconds")
        if output:
            path = Path(output); suffix = path.suffix.lower(); preview = "video" if suffix in {".mp4", ".webm", ".ogg", ".mov", ".m4v"} else "audio" if suffix in {".mp3", ".m4a", ".opus", ".wav", ".oga"} else ""
            job.result = {"file": output, "folder": str(path.parent), "size": path.stat().st_size, "status": "Готово", "preview_type": preview, "preview_url": f"/api/media?path={quote(output)}"}
        self._publish(job, reason)
        try: add_history(HistoryEntry(id=job.id, job_id=job.id, datetime=job.completed_at, completed_at=job.completed_at, url=job.request.url, title=Path(output).stem if output else job.request.filename_template, download_dir=job.request.download_dir, output_file=output, mode=job.request.download_mode, format=job.request.selected_format, status=status, error="" if status == "success" else reason, reason=reason, filename_template=job.request.filename_template, quality_key=quality_key(job.request), size=job.result.get("size", 0), attempts=job.attempts, request_snapshot=job.request.model_dump()))
        except Exception as exc: self._safe_log(job, f"Не удалось записать историю: {exc}")

    def retry(self, job_id: str) -> bool:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job or job.status not in {"error", "interrupted", "retry_wait", "stopped"}: return False
            if job.status == "retry_wait":
                if job.cancel_event.is_set(): return False
                job.retry_now.set(); return True
            self._conflict(windows_path_key(job.output_template), job.request, job)
            self._claim(job)
            job.resuming = True
            job.cancel_event.clear(); job.retry_now.clear(); job.status = job.stage = "queued"
            job.completed_at = ""; job.next_retry_at = ""
        self._launch(job)
        return True

    def stop(self, job_id: str = "") -> bool:
        targets = [self.jobs[job_id]] if job_id in self.jobs else list(self.jobs.values()) if not job_id else []; changed = False
        for job in targets:
            if job.status not in ACTIVE: continue
            changed = True; job.cancel_event.set(); self._terminate(job)
            # Only the worker may mark completion and release its run lease.
        return changed

    def _terminate(self, job: DownloadJob) -> None:
        process = job.process
        if process is None or process.poll() is not None: return
        try:
            if os.name == "nt": process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else: process.terminate()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            if os.name == "nt": subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, shell=False)
            else: process.kill()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: pass
        finally:
            pass  # the reader owns and closes stdout after the process exits

    def shutdown(self) -> None:
        self.stop(); self._persist()
