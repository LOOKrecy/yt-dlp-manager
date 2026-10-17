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
from app.json_store import atomic_write, read
from app.models import DownloadRequest, HistoryEntry
from app.path_utils import JOBS_PATH, LOGS_DIR, build_output_template, ensure_project_dirs, ensure_writable_directory
from app.recovery import Failure, classify_failure, retry_delay
from app.text_utils import decode_process_output
from app.ytdlp_service import build_download_command, quality_key, quote_command

ACTIVE = {"queued", "preparing", "downloading", "retry_wait", "postprocessing"}
TERMINAL = {"stopped", "error", "success", "interrupted"}
PROGRESS_RE = re.compile(r"\[download\]\s+(?P<percent>[\d.]+)%\s+of\s+(?P<size>.+?)(?:\s+in\s+(?P<elapsed>\S+))?(?:\s+at\s+(?P<speed>\S+))?\s*$")

@dataclass
class DownloadJob:
    id: str
    request: DownloadRequest
    output_template: str
    status: str = "queued"
    process: subprocess.Popen[bytes] | None = None
    attempt: int = 0
    attempt_id: str = ""
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
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    retry_now: threading.Event = field(default_factory=threading.Event, repr=False)
    diagnostic_tail: deque[str] = field(default_factory=lambda: deque(maxlen=80), repr=False)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "attempt": self.attempt, "max_restarts": self.request.max_restarts,
                "return_code": self.return_code, "reason": self.reason, "next_retry_at": self.next_retry_at,
                "progress": self.progress, "downloaded_bytes": self.downloaded_bytes, "total_bytes": self.total_bytes,
                "speed": self.speed, "eta": self.eta, "stream": self.stream, "stage": self.stage,
                "result": dict(self.result), "running": self.process is not None and self.process.poll() is None,
                "url": self.request.url, "filename": self.request.filename_template, "started_at": self.started_at,
                "completed_at": self.completed_at, "attempts": list(self.attempts),
                "access_summary": {"proxy": self.request.proxy_enabled, "cookies": self.request.cookies_enabled, "section": self.request.section_enabled}}

    def stored(self) -> dict[str, Any]:
        data = self.public(); data["request"] = self.request.model_dump(); data["output_template"] = self.output_template; data["manifest"] = self.manifest
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
        self._wait = wait or (lambda event, seconds: event.wait(seconds)); self.broker = EventBroker(); self._reserved: dict[str, str] = {}
        self._slots = threading.BoundedSemaphore(2); self._load_jobs()

    def configure(self, maximum: int) -> None:
        # Applied for new process lifetime; changing live semaphore would race active jobs.
        if not any(j.status in ACTIVE for j in self.jobs.values()): self._slots = threading.BoundedSemaphore(maximum)

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
                job = DownloadJob(raw["id"], request, raw["output_template"], status=status, attempt=raw.get("attempt", 0), reason="Работа backend была прервана" if status == "interrupted" else raw.get("reason", ""), result=raw.get("result", {}), attempts=raw.get("attempts", []), manifest=raw.get("manifest", []), started_at=raw.get("started_at", ""), completed_at=raw.get("completed_at", ""))
                self.jobs[job.id] = job; self._reserved[job.output_template.casefold()] = job.id
            except Exception: continue

    def snapshot(self) -> dict[str, Any]:
        with self._lock: jobs = sorted((j.public() for j in self.jobs.values()), key=lambda x: x["started_at"], reverse=True)
        return {"revision": self.broker.revision, "jobs": jobs, "running_count": sum(j["status"] in ACTIVE for j in jobs)}

    def get_logs(self) -> dict[str, Any]: return self.snapshot()
    def log_tail(self, job_id: str, limit: int = 300) -> list[str]:
        path = LOGS_DIR / f"{job_id}.log"
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(limit, 2000)):] if path.exists() else []

    def clear_logs(self) -> None:
        # Only clear the visible tails/files explicitly; job state is untouched.
        for job_id in list(self.jobs): (LOGS_DIR / f"{job_id}.log").unlink(missing_ok=True)

    def start_download(self, request: DownloadRequest) -> str:
        ensure_project_dirs(); directory = ensure_writable_directory(request.download_dir)
        job_id = str(uuid.uuid4())
        if not request.filename_template: request = request.model_copy(update={"filename_template": f"download-{job_id[:8]}"})
        template = build_output_template(directory, request.filename_template); key = template.casefold()
        with self._lock:
            owner = self._reserved.get(key)
            if owner and self.jobs.get(owner) and self.jobs[owner].status not in {"success"}: raise ValueError("Этот целевой путь уже зарезервирован другим заданием")
            job = DownloadJob(job_id, request.model_copy(deep=True), template); self.jobs[job.id] = job; self._reserved[key] = job.id
        self._persist(); threading.Thread(target=self._worker, args=(job,), daemon=True).start(); return job.id

    def _worker(self, job: DownloadJob) -> None:
        with self._slots:
            if job.cancel_event.is_set(): return self._finish(job, "stopped", "Остановлено до запуска")
            cdn_refreshes = 0
            while True:
                job.attempt += 1; job.attempt_id = str(uuid.uuid4()); current = job.attempt_id; job.status = job.stage = "preparing"; job.next_retry_at = ""; job.diagnostic_tail.clear()
                args = build_download_command(job.request, job.attempt, job.output_template)
                safe_args = self._redact_args(args)
                self._append_log(job.id, f"=== attempt {job.attempt} ({current}) ===\nargv-json: {json.dumps(safe_args, ensure_ascii=False)}\ncmd-display (не для shell): {quote_command(safe_args)}")
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
                        job.manifest.append(str(result_path)); return self._finish(job, "success", "Готово", str(result_path))
                assert failure is not None
                job.reason = failure.message; job.return_code = code
                allowed = job.request.auto_retry and job.attempt <= job.request.max_restarts
                if failure.action == "refresh_once":
                    allowed = allowed and cdn_refreshes < 1; cdn_refreshes += 1
                elif failure.action not in {"retry", "retry_429"}: allowed = False
                if not allowed: return self._finish(job, "error", failure.message)
                delay = failure.retry_after or retry_delay(job.attempt)
                job.status = job.stage = "retry_wait"; job.next_retry_at = (datetime.now() + timedelta(seconds=delay)).isoformat(timespec="seconds"); self._persist(); self.emit("job", failure.message, job.id, job=job.public())
                job.retry_now.clear()
                deadline = time.monotonic() + delay
                while not job.cancel_event.is_set() and not job.retry_now.is_set() and time.monotonic() < deadline:
                    self._wait(job.cancel_event, min(.25, max(0, deadline - time.monotonic())))
                if job.cancel_event.is_set(): return self._finish(job, "stopped", "Остановлено во время ожидания")

    def _run_attempt(self, job: DownloadJob, args: list[str], attempt_id: str) -> tuple[int, str]:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0  # type: ignore[attr-defined]
        try: process = self._popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0, shell=False, creationflags=flags)
        except OSError as exc: job.diagnostic_tail.append(str(exc)); return 127, ""
        with self._lock:
            if job.attempt_id != attempt_id: return 1, ""
            job.process = process
        if job.cancel_event.is_set(): self._terminate(job)
        job.status = job.stage = "downloading"; result = ""; assert process.stdout is not None
        for raw in process.stdout:
            text = decode_process_output(raw).rstrip("\r\n"); job.diagnostic_tail.append(text); self._append_log(job.id, text)
            if text.startswith("__YTM_PROGRESS__"): self._progress(job, text[len("__YTM_PROGRESS__"):], attempt_id)
            elif text.startswith("__YTM_RESULT__"): result = text[len("__YTM_RESULT__"):].strip()
        code = process.wait(); job.return_code = code
        with self._lock:
            if job.attempt_id == attempt_id: job.process = None
        return code, result

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
        hidden = {"--proxy", "--cookies", "--add-header", "--username", "--password", "--video-password"}; result = list(args)
        for i, arg in enumerate(result[:-1]):
            if arg in hidden: result[i + 1] = "***"
        if result:
            from urllib.parse import urlsplit, urlunsplit
            try:
                parts = urlsplit(result[-1])
                if parts.scheme and parts.query: result[-1] = urlunsplit((parts.scheme, parts.netloc, parts.path, "…", ""))
            except ValueError: pass
        return result

    def _finish(self, job: DownloadJob, status: str, reason: str, output: str = "") -> None:
        job.status = job.stage = status; job.reason = reason; job.next_retry_at = ""; job.completed_at = datetime.now().isoformat(timespec="seconds")
        if output:
            path = Path(output); job.result = {"file": output, "folder": str(path.parent), "size": path.stat().st_size, "preview_url": f"/api/media?path={quote(output)}"}
        self._persist(); self.emit("job", reason, job.id, job=job.public())
        add_history(HistoryEntry(id=job.id, job_id=job.id, datetime=job.completed_at, completed_at=job.completed_at, url=job.request.url, title=Path(output).stem if output else job.request.filename_template, download_dir=job.request.download_dir, output_file=output, mode=job.request.download_mode, format=job.request.selected_format, status=status, error="" if status == "success" else reason, reason=reason, filename_template=job.request.filename_template, quality_key=quality_key(job.request), size=job.result.get("size", 0), attempts=job.attempts, request_snapshot=job.request.model_dump()))

    def retry(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status not in {"error", "interrupted", "retry_wait"}: return False
        if job.status == "retry_wait": job.retry_now.set(); return True
        job.cancel_event.clear(); job.retry_now.clear(); job.status = "queued"; threading.Thread(target=self._worker, args=(job,), daemon=True).start(); return True

    def stop(self, job_id: str = "") -> bool:
        targets = [self.jobs[job_id]] if job_id in self.jobs else list(self.jobs.values()) if not job_id else []; changed = False
        for job in targets:
            if job.status not in ACTIVE: continue
            changed = True; job.cancel_event.set(); self._terminate(job)
            if job.process is None: self._finish(job, "stopped", "Остановлено пользователем")
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
            if process.stdout: process.stdout.close()

    def shutdown(self) -> None:
        self.stop(); self._persist()
