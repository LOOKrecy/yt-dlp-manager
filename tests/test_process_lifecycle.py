import io

from app.models import DownloadRequest
from app.process_manager import DownloadJob, ProcessManager


class FakeProcess:
    def __init__(self, lines, code=0):
        self.stdout = io.BytesIO(b"".join(line.encode() + b"\n" for line in lines))
        self.code = code
        self.pid = 123
    def poll(self): return None
    def wait(self, timeout=None): return self.code
    def terminate(self): pass
    def kill(self): pass


class BrokenOutput:
    def __iter__(self): return self
    def __next__(self): raise OSError("read failed")
    def close(self): pass


class BrokenProcess(FakeProcess):
    def __init__(self):
        super().__init__([]); self.stdout = BrokenOutput()


def test_attempt_publishes_process_and_download_transitions(tmp_path, monkeypatch):
    process = FakeProcess(["metadata", "__YTM_PROGRESS__10|100|NA|20|4|v1"])
    manager = ProcessManager(popen=lambda *a, **k: process)
    events = []
    monkeypatch.setattr(manager, "_publish", lambda job, message: events.append((job.stage, message)))
    monkeypatch.setattr(manager, "_safe_log", lambda *args: None)
    job = DownloadJob("job", DownloadRequest(url="https://example.test", filename_template="x"), str(tmp_path / "x.%(ext)s"), attempt_id="attempt")
    code, _ = manager._run_attempt(job, ["yt-dlp"], "attempt")
    assert code == 0
    assert events[0][1].startswith("yt-dlp запущен")
    assert ("downloading", "Скачивание") in events


def test_worker_exception_cannot_leave_preparing(monkeypatch, tmp_path):
    import app.process_manager as module
    manager = ProcessManager()
    job = DownloadJob("job", DownloadRequest(url="https://example.test", filename_template="x"), str(tmp_path / "x.%(ext)s"))
    monkeypatch.setattr(module, "build_download_command", lambda *args: (_ for _ in ()).throw(ValueError("bad argv")))
    monkeypatch.setattr(manager, "_publish", lambda *args: None)
    monkeypatch.setattr(manager, "_safe_log", lambda *args: None)
    monkeypatch.setattr(manager, "_finish", lambda target, status, reason, output="": setattr(target, "status", status))
    manager._worker(job)
    assert job.status == "error"


def test_stopped_job_can_continue(monkeypatch, tmp_path):
    manager = ProcessManager()
    job = DownloadJob("job", DownloadRequest(url="https://example.test", filename_template="x"), str(tmp_path / "x.%(ext)s"), status="stopped", stage="stopped")
    manager.jobs[job.id] = job
    monkeypatch.setattr(manager, "_worker", lambda target: None)
    monkeypatch.setattr(manager, "_publish", lambda *args: None)
    assert manager.retry(job.id)
    assert job.status == "queued"


def test_read_exception_reaches_error_state(monkeypatch, tmp_path):
    import app.process_manager as module
    manager = ProcessManager(popen=lambda *args, **kwargs: BrokenProcess())
    job = DownloadJob("job", DownloadRequest(url="https://example.test", filename_template="x"), str(tmp_path / "x.%(ext)s"))
    monkeypatch.setattr(module, "build_download_command", lambda *args: ["yt-dlp"])
    monkeypatch.setattr(manager, "_publish", lambda *args: None)
    monkeypatch.setattr(manager, "_safe_log", lambda *args: None)
    monkeypatch.setattr(manager, "_finish", lambda target, status, reason, output="": setattr(target, "status", status))
    manager._worker(job)
    assert job.status == "error"


def test_timeouts_retry_then_succeed_with_one_logical_job(monkeypatch, tmp_path):
    import app.process_manager as module
    output = tmp_path / "done.mp4"; output.write_bytes(b"media")
    manager = ProcessManager()
    job = DownloadJob("same-job", DownloadRequest(url="https://example.test", filename_template="x", max_restarts=2), str(tmp_path / "x.%(ext)s"))
    manager._wait = lambda event, seconds: (job.retry_now.set() or True)
    results = iter([(1, ""), (1, ""), (0, str(output))])
    monkeypatch.setattr(module, "build_download_command", lambda *args: ["yt-dlp"])
    def attempt(target, args, attempt_id):
        code, path = next(results)
        if code: target.diagnostic_tail.append("Read timed out")
        return code, path
    monkeypatch.setattr(manager, "_run_attempt", attempt)
    monkeypatch.setattr(manager, "_publish", lambda *args: None)
    monkeypatch.setattr(manager, "_safe_log", lambda *args: None)
    finished = []
    monkeypatch.setattr(manager, "_finish", lambda target, status, reason, output="": (setattr(target, "status", status), finished.append((target.id, status, output))))
    manager._worker(job)
    assert job.attempt == 3 and finished == [("same-job", "success", str(output))]


def test_cancel_during_retry_wait_stops_without_next_attempt(monkeypatch, tmp_path):
    import app.process_manager as module
    manager = ProcessManager(wait=lambda event, seconds: (event.set() or True))
    job = DownloadJob("job", DownloadRequest(url="https://example.test", filename_template="x"), str(tmp_path / "x.%(ext)s"))
    calls = []
    monkeypatch.setattr(module, "build_download_command", lambda *args: ["yt-dlp"])
    def attempt(target, args, attempt_id): calls.append(1); target.diagnostic_tail.append("Read timed out"); return 1, ""
    monkeypatch.setattr(manager, "_run_attempt", attempt)
    monkeypatch.setattr(manager, "_publish", lambda *args: None)
    monkeypatch.setattr(manager, "_safe_log", lambda *args: None)
    monkeypatch.setattr(manager, "_finish", lambda target, status, reason, output="": setattr(target, "status", status))
    manager._worker(job)
    assert job.status == "stopped" and len(calls) == 1


def test_success_calls_fragment_fix_and_builds_preview(monkeypatch, tmp_path):
    import app.process_manager as module
    output = tmp_path / "clip.mp4"; output.write_bytes(b"media")
    manager = ProcessManager()
    request = DownloadRequest(url="https://example.test", filename_template="x", section_enabled=True, section_keyframe_fix=True, section_end="00:00:10")
    job = DownloadJob("job", request, str(tmp_path / "x.%(ext)s"))
    monkeypatch.setattr(module, "build_download_command", lambda *args: ["yt-dlp"])
    monkeypatch.setattr(manager, "_run_attempt", lambda *args: (0, str(output)))
    fixed = []
    monkeypatch.setattr(manager, "_fix_section_start", lambda target, path: fixed.append(path))
    monkeypatch.setattr(manager, "_publish", lambda *args: None)
    monkeypatch.setattr(manager, "_safe_log", lambda *args: None)
    monkeypatch.setattr(module, "add_history", lambda *args: None)
    manager._worker(job)
    assert fixed == [output] and job.status == "success"
    assert job.result["preview_type"] == "video" and job.result["status"] == "Готово"
