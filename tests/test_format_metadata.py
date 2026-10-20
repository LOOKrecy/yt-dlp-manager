import json
import math

import pytest

from app.ytdlp_service import classify_stream, codec_state, parse_formats_metadata


def parse(item, **metadata):
    return parse_formats_metadata(json.dumps({'formats': [{'format_id': 'id', **item}], **metadata}))[0][0]


@pytest.mark.parametrize('item,kind', [
    ({'vcodec': 'none', 'acodec': None, 'resolution': 'audio only', 'ext': 'mp4'}, 'audio'),
    ({'vcodec': 'none', 'acodec': 'aac'}, 'audio'),
    ({'vcodec': 'avc1', 'acodec': 'none'}, 'video'),
    ({'vcodec': 'avc1', 'acodec': 'aac'}, 'muxed'),
    ({}, 'unknown'),
    ({'resolution': 'audio only', 'acodec': 'unknown'}, 'audio'),
    ({'vcodec': 'none', 'audio_ext': 'm4a'}, 'audio'),
    ({'width': 1280, 'acodec': 'none'}, 'video'),
    ({'video_ext': 'mp4', 'audio_ext': 'none'}, 'video'),
    ({'ext': 'mp4', 'format_id': 'audio-123', 'protocol': 'm3u8_native'}, 'unknown'),
    ({'vcodec': 'avc1', 'resolution': 'audio only'}, 'unknown'),
    ({'vcodec': 'none', 'height': 720, 'acodec': 'aac'}, 'unknown'),
    ({'vcodec': 'none', 'acodec': 'none'}, 'unknown'),
    ({'acodec': 'aac'}, 'unknown'),
])
def test_stream_evidence(item, kind):
    result = parse(item)
    assert result.kind == kind
    assert result.kind_reason


def test_distinct_codec_states():
    assert [codec_state(item, 'vcodec') for item in [{}, {'vcodec': None}, {'vcodec': ''}, {'vcodec': 'none'}, {'vcodec': 'unknown'}, {'vcodec': 'avc'}]] == ['missing', 'null', 'empty', 'absent', 'unknown', 'known']


@pytest.mark.parametrize('values,size,source', [
    ({'filesize': 1000, 'filesize_approx': 2000}, 1000, 'exact'),
    ({'filesize_approx': 2000}, 2000, 'extractor_estimate'),
    ({'tbr': 2000}, 150000000, 'bitrate_estimate'),
    ({'vcodec': 'none', 'acodec': 'aac', 'abr': 128}, 9600000, 'bitrate_estimate'),
    ({'vcodec': 'avc', 'acodec': 'none', 'vbr': 1000, 'tbr': 2000}, 75000000, 'bitrate_estimate'),
    ({'tbr': 2000, 'vbr': 1800, 'abr': 128}, 150000000, 'bitrate_estimate'),
    ({'vbr': 1800, 'abr': 200}, 150000000, 'bitrate_estimate'),
    ({'vbr': 1800}, None, 'unknown'),
    ({}, None, 'unknown'),
])
def test_sizes(values, size, source):
    result = parse({'vcodec': 'avc', 'acodec': 'aac', **values}, duration=600)
    assert (result.size_bytes, result.size_source) == (size, source)


@pytest.mark.parametrize('bad', [None, True, False, -100, 0, math.nan, math.inf, -math.inf, '1000'])
def test_invalid_sizes_and_bitrates_are_not_numbers(bad):
    result = parse({'vcodec': 'avc', 'acodec': 'none', 'filesize': bad, 'filesize_approx': bad, 'vbr': bad, 'tbr': bad}, duration=600)
    assert result.size_bytes is None and result.size_source == 'unknown'
    assert result.model_dump()['size_bytes'] is None


def test_format_duration_precedes_video_duration_and_no_global_bitrate():
    result = parse({'vcodec': 'none', 'resolution': 'audio only', 'abr': 128, 'duration': 60}, duration=600)
    assert result.size_bytes == 960000
    assert parse({'resolution': 'audio only'}, duration=600, tbr=2000).size_bytes is None
    assert parse({'resolution': 'audio only', 'abr': 128}, is_live=True).size_bytes is None
