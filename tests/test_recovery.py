from pathlib import Path

import pytest

from app.models import DownloadRequest
from app.recovery import classify_failure, retry_delay
from app.ytdlp_service import _split_windows_commandline, build_download_command


def test_error_classification_uses_terminal_tail_and_policies():
    assert classify_failure("downloading", 1, ["old timeout", "HTTP Error 401: Unauthorized"]).action == "user"
    assert classify_failure("downloading", 1, ["HTTP Error 503"]).action == "retry"
    limited = classify_failure("downloading", 1, ["HTTP Error 429", "Retry-After: 12"])
    assert limited.action == "retry_429" and limited.retry_after == 60
    assert classify_failure("downloading", 1, ["HTTP Error 403"]).action == "refresh_once"
    assert classify_failure("postprocessing", 1, ["conversion failed"]).action == "postprocess"
    assert classify_failure("downloading", 1, ["No space left on device"]).action == "fatal"


def test_backoff_is_bounded():
    assert [retry_delay(i) for i in range(1, 7)] == [5, 10, 20, 40, 60, 60]


def test_windows_extra_args_preserve_paths_and_reject_lifecycle_options():
    assert _split_windows_commandline(r'--write-thumbnail --cookies-from-browser "C:\Мои файлы\Chrome"')[-1] == r"C:\Мои файлы\Chrome"
    with pytest.raises(ValueError, match="запрещён"):
        _split_windows_commandline('--no-part --output=x')
    with pytest.raises(ValueError, match="незакрытая"):
        _split_windows_commandline('"unfinished')


def test_retry_command_keeps_stable_output_and_drops_force_overwrite(monkeypatch, tmp_path):
    import app.ytdlp_service as service
    executable = tmp_path / "yt-dlp.exe"; executable.write_bytes(b"x")
    monkeypatch.setattr(service, "YT_DLP_PATH", executable)
    request = DownloadRequest(url="https://example.test/watch?v=1", download_dir=str(tmp_path), filename_template="Имя с пробелом", conflict_policy="overwrite", socket_timeout=31)
    first = build_download_command(request, 1)
    retry = build_download_command(request, 2)
    assert "--force-overwrites" in first and "--force-overwrites" not in retry
    assert "--continue" in retry and "--part" in retry and "--ignore-config" in retry
    assert retry[-1] == request.url
    assert retry[retry.index("-o") + 1] == first[first.index("-o") + 1]
