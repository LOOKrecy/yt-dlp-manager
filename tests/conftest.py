"""All manager/history filesystem effects stay under pytest's temporary root."""
import pytest


@pytest.fixture(autouse=True)
def isolate_job_storage(tmp_path, monkeypatch):
    import app.process_manager as manager
    import app.history_manager as history
    monkeypatch.setattr(manager, 'JOBS_PATH', tmp_path / 'jobs.json')
    monkeypatch.setattr(manager, 'LOGS_DIR', tmp_path / 'logs')
    monkeypatch.setattr(manager, 'ensure_project_dirs', lambda: None)
    monkeypatch.setattr(history, 'ensure_project_dirs', lambda: None)
    monkeypatch.setattr(history, 'HISTORY_PATH', tmp_path / 'history.json')
