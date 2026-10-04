from app.models import DownloadRequest
from app.process_manager import PROGRESS_RE
from app.ytdlp_service import parse_formats, quality_key


def test_progress_line_is_parsed():
    match = PROGRESS_RE.search('[download] 100% of    3.15MiB in 00:00:02 at 1.27MiB/s')
    assert match
    assert match.group('percent') == '100'
    assert match.group('size').strip() == '3.15MiB'
    assert match.group('speed') == '1.27MiB/s'


def test_format_size_with_approximation_marker():
    items = parse_formats('http-2176 mp4 720x1280 │ ≈  5.45MiB 2176k https │ unknown unknown')
    assert items[0].size == '5.45 MiB'
    assert items[0].size_bytes == int(5.45 * 1024**2)


def test_quality_identity_does_not_include_filename():
    first = DownloadRequest(url='https://example.test/video', filename_template='one', download_mode='manual', selected_format='137+140')
    second = first.model_copy(update={'filename_template': 'two'})
    assert quality_key(first) == quality_key(second)
