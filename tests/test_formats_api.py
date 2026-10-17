import pytest
from fastapi import HTTPException

from app.main import get_formats
from app.models import FormatRequest


class Completed:
    def __init__(self, code=0, stdout=b"", stderr=b""):
        self.returncode = code; self.stdout = stdout; self.stderr = stderr


def prepare(monkeypatch, tmp_path, completed):
    import app.ytdlp_service as service
    executable = tmp_path / "yt-dlp.exe"; executable.write_bytes(b"x")
    monkeypatch.setattr(service, "YT_DLP_PATH", executable)
    monkeypatch.setattr("app.main.subprocess.run", lambda *args, **kwargs: completed)


def test_formats_api_rejects_invalid_metadata(monkeypatch, tmp_path):
    prepare(monkeypatch, tmp_path, Completed(stdout=b'{"formats":['))
    with pytest.raises(HTTPException, match="JSON"):
        get_formats(FormatRequest(url="https://example.test/video"))


def test_formats_api_does_not_expose_cdn_url(monkeypatch, tmp_path):
    payload = '{"id":"x","formats":[{"format_id":"1","vcodec":"avc","acodec":"none","url":"https://cdn.test/?token=secret"}]}'
    prepare(monkeypatch, tmp_path, Completed(stdout=payload.encode()))
    data = get_formats(FormatRequest(url="https://example.test/video"))
    assert data["success"] and "cdn.test" not in str(data) and "secret" not in str(data)


def test_formats_api_checks_return_code_before_stdout(monkeypatch, tmp_path):
    prepare(monkeypatch, tmp_path, Completed(1, b'{"formats":[]}', b"ERROR: denied"))
    data = get_formats(FormatRequest(url="https://example.test/video"))
    assert data["success"] is False and data["formats"] == [] and "denied" in data["error"]
