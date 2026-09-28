from __future__ import annotations

import json
from pathlib import Path

from app.path_utils import FFMPEG_PATH, FFPROBE_PATH

START_TOLERANCE_SECONDS = 0.05


def build_frame_probe_command(path: Path) -> list[str]:
    """Inspect decoded video frames, rather than trusting container key-frame flags."""
    return [
        str(FFPROBE_PATH),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time,pkt_dts_time,pkt_size,pict_type",
        "-of", "json",
        str(path),
    ]


def find_first_decoded_keyframe(raw_output: str) -> tuple[float | None, int]:
    """Return the first real I-frame timestamp and packet size from ffprobe frame data."""
    try:
        frames = json.loads(raw_output).get("frames", [])
    except (json.JSONDecodeError, AttributeError) as exc:
        raise ValueError("ffprobe вернул некорректные данные о кадрах") from exc

    for frame in frames:
        if frame.get("pict_type") != "I":
            continue
        try:
            packet_size = int(frame.get("pkt_size", 0))
            timestamp = float(frame.get("best_effort_timestamp_time", frame.get("pkt_dts_time")))
        except (TypeError, ValueError):
            continue
        # A decoded I picture with a real packet is used deliberately. Container
        # key_frame flags are not requested because they can be wrong after a cut.
        if packet_size > 0 and timestamp >= 0:
            return timestamp, packet_size
    return None, 0


def needs_keyframe_trim(timestamp: float | None) -> bool:
    return timestamp is not None and timestamp > START_TOLERANCE_SECONDS


def temporary_output_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.keyframe-fix{path.suffix}")


def build_keyframe_trim_command(path: Path, timestamp: float) -> tuple[list[str], Path]:
    temporary = temporary_output_path(path)
    command = [
        str(FFMPEG_PATH),
        "-y",
        "-ss", f"{timestamp:.6f}",
        "-i", str(path),
        "-map", "0",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(temporary),
    ]
    return command, temporary
