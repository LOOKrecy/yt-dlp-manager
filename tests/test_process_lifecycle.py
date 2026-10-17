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
