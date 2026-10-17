from pathlib import Path

import pytest

from app.models import DownloadRequest
from app.recovery import classify_failure, retry_delay
from app.ytdlp_service import _split_windows_commandline, build_download_command, parse_formats_metadata


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
    assert "--progress" in retry and "--no-quiet" in retry


def test_strict_metadata_is_compact_and_rejects_invalid_json():
    raw = '{"id":"sample","title":"Русское имя","formats":[{"format_id":"v1","ext":"mp4","vcodec":"avc1","acodec":"none","fps":30,"filesize_approx":123,"url":"https://cdn.test/secret?token=x"},{"format_id":"a1","ext":"m4a","vcodec":"none","acodec":"aac","language":"ru","format_note":"Русская дорожка"}]}'
    items, diagnostic = parse_formats_metadata(raw)
    assert [item.kind for item in items] == ["video", "audio"]
    assert items[0].approximate is True and items[1].approximate is False
    assert all("cdn.test" not in item.model_dump_json() for item in items)
    assert diagnostic == {"id": "sample", "title": "Русское имя", "format_count": 2}
    with pytest.raises(ValueError, match="JSON"):
        parse_formats_metadata('{"id":"sample","formats":[')
    with pytest.raises(ValueError, match="format_id"):
        parse_formats_metadata('{"formats":[{"ext":"mp4"}]}')
