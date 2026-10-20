from __future__ import annotations

import json
import math
import subprocess
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from app.models import DownloadRequest, FormatItem, FormatRequest
from app.path_utils import FFMPEG_PATH, FFPROBE_PATH, YT_DLP_PATH, build_output_template, ensure_writable_directory, find_deno_path, resolve_user_path

FALLBACK_IMPERSONATE_TARGETS = ["chrome", "chrome-110", "chrome-120", "edge", "safari", "firefox"]


def quote_command(args: list[str]) -> str:
    """Human CMD approximation. JSON argv remains the authoritative diagnostic."""
    return subprocess.list2cmdline([str(arg) for arg in args])


def redact_args(args: list[str]) -> list[str]:
    hidden = {"--proxy", "--cookies", "--add-header", "--username", "--password", "--video-password"}
    result = list(args)
    for index, argument in enumerate(result[:-1]):
        if argument in hidden:
            result[index + 1] = "***"
    for index, argument in enumerate(result):
        name, separator, _ = argument.partition("=")
        if separator and name in hidden:
            result[index] = f"{name}=***"
    if result:
        try:
            parts = urlsplit(result[-1])
            if parts.scheme and parts.query:
                result[-1] = urlunsplit((parts.scheme, parts.netloc, parts.path, "…", ""))
        except ValueError:
            pass
    return result


def redact_diagnostic_text(text: str) -> str:
    """Best-effort redaction for bounded stderr shown through the local UI."""
    redacted = text
    sensitive = r"(?:proxy|cookies?|add-header|username|password|video-password)"
    redacted = re.sub(rf"(?i)(--{sensitive})(?:=|\s+)(?:\"[^\"]*\"|'[^']*'|\S+)", r"\1=***", redacted)
    redacted = re.sub(r"(?i)(https?://[^\s?#]+)\?[^\s]+", r"\1?…", redacted)
    redacted = re.sub(r"(?i)(authorization|cookie|token|api[_-]?key)(\s*[:=]\s*)[^\s,;]+", r"\1\2***", redacted)
    return redacted


def split_extra_args(extra_args: str) -> list[str]:
    if not (extra_args or "").strip():
        return []
    try:
        # CommandLineToArgvW-compatible parsing without invoking cmd.exe.
        return _split_windows_commandline(extra_args)
    except ValueError as exc:
        raise ValueError(f"Не удалось разобрать дополнительные параметры: {exc}") from exc


def _split_windows_commandline(command: str) -> list[str]:
    result: list[str] = []; current: list[str] = []; quoted = False; slashes = 0; i = 0
    while i < len(command):
        char = command[i]
        if char == "\\": slashes += 1; i += 1; continue
        if char == '"':
            current.extend("\\" * (slashes // 2))
            if slashes % 2: current.append('"')
            else: quoted = not quoted
            slashes = 0; i += 1; continue
        current.extend("\\" * slashes); slashes = 0
        if char.isspace() and not quoted:
            if current: result.append("".join(current)); current = []
        else: current.append(char)
        i += 1
    current.extend("\\" * slashes)
    if quoted: raise ValueError("незакрытая двойная кавычка")
    if current: result.append("".join(current))
    _reject_conflicting_args(result)
    return result


def _reject_conflicting_args(args: list[str]) -> None:
    forbidden = {"--no-continue", "--no-part", "--force-overwrites", "--no-progress", "--exec", "-o", "--output", "-p", "-P", "--paths", "--print", "--progress-template", "--playlist-items", "--yes-playlist", "--max-downloads"}
    for arg in args:
        name = arg.split("=", 1)[0]
        if name in forbidden or (name.startswith("-o") and name != "--") or (name.startswith("-P") and name != "--"):
            raise ValueError(f"Параметр {name} запрещён: он нарушает гарантии докачки и диагностики")


def validate_access_args(request: FormatRequest | DownloadRequest) -> None:
    if not request.url.strip():
        raise ValueError("URL не указан")
    if request.proxy_enabled and not request.proxy.strip():
        raise ValueError("Proxy включён, но строка proxy пустая")
    if request.cookies_enabled:
        if not request.cookies_file.strip():
            raise ValueError("Cookies-файл включён, но путь не указан")
        cookies_path = resolve_user_path(request.cookies_file, None)
        if not cookies_path.exists() or not cookies_path.is_file():
            raise ValueError(f"Cookies-файл не найден: {cookies_path}")
    if request.impersonate_enabled and not request.impersonate_target.strip():
        raise ValueError("Impersonate включён, но browser target не выбран")


def add_access_args(args: list[str], request: FormatRequest | DownloadRequest) -> None:
    if request.proxy_enabled:
        args.extend(["--proxy", request.proxy.strip()])
    if request.cookies_enabled:
        args.extend(["--cookies", str(resolve_user_path(request.cookies_file, None))])
    if request.impersonate_enabled:
        args.extend(["--impersonate", request.impersonate_target.strip()])


def add_deno_runtime_arg(args: list[str], request: FormatRequest | DownloadRequest) -> None:
    if not request.deno_enabled:
        return
    deno_path = find_deno_path()
    if deno_path is not None:
        args.extend(["--js-runtimes", f"deno:{deno_path}"])


def add_download_mode_args(args: list[str], request: DownloadRequest) -> None:
    if request.download_mode == "video":
        args.extend(["-f", "bestvideo+bestaudio/best"])
    elif request.download_mode == "video_only":
        args.extend(["-f", "bestvideo"])
    elif request.download_mode == "audio":
        args.extend(["-x", "--audio-format", request.audio_format])
    else:
        args.extend(["-f", request.selected_format.strip()])


def add_section_args(args: list[str], request: DownloadRequest) -> None:
    if request.section_enabled:
        args.extend(["--download-sections", f"*{request.section_start}-{request.section_end}"])


def build_output_probe_command(request: DownloadRequest) -> list[str]:
    validate_download_request(request)
    download_dir = ensure_writable_directory(request.download_dir)
    args = [str(YT_DLP_PATH), "--skip-download", "--print", "filename"]
    add_deno_runtime_arg(args, request)
    add_access_args(args, request)
    add_download_mode_args(args, request)
    add_section_args(args, request)
    args.extend(["-o", build_output_template(download_dir, request.filename_template)])
    args.extend(split_extra_args(request.extra_args))
    args.append(request.url.strip())
    return args


def suggest_non_conflicting_filename(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError("Не удалось подобрать свободное имя файла")


def template_name_from_path(path: Path) -> str:
    return path.stem


def parse_time(value: str) -> int:
    parts = (value or "").strip().split(":")
    if len(parts) != 3:
        raise ValueError("Время должно быть в формате HH:MM:SS")
    try:
        hours, minutes, seconds = [int(part) for part in parts]
    except ValueError as exc:
        raise ValueError("Время должно содержать только числа") from exc
    if hours < 0 or not 0 <= minutes <= 59 or not 0 <= seconds <= 59:
        raise ValueError("Некорректное время фрагмента")
    return hours * 3600 + minutes * 60 + seconds


def validate_download_request(request: DownloadRequest) -> None:
    validate_access_args(request)
    if not YT_DLP_PATH.exists():
        raise ValueError("yt-dlp.exe не найден в папке bin")
    if request.section_enabled:
        if not FFMPEG_PATH.exists():
            raise ValueError("ffmpeg.exe не найден: он нужен для загрузки фрагментов")
        start = parse_time(request.section_start)
        end = parse_time(request.section_end)
        if end <= start:
            raise ValueError("Конец фрагмента должен быть больше начала")
        if request.section_keyframe_fix and not FFPROBE_PATH.exists():
            raise ValueError("ffprobe.exe не найден: он нужен для поиска первого ключевого кадра")
    if request.download_mode == "manual" and not request.selected_format.strip():
        raise ValueError("В ручном режиме формат не выбран")
    ensure_writable_directory(request.download_dir)


def build_format_command(request: FormatRequest) -> list[str]:
    validate_access_args(request)
    if not YT_DLP_PATH.exists():
        raise ValueError("yt-dlp.exe не найден в папке bin")
    args = [str(YT_DLP_PATH), "--ignore-config", "--dump-single-json", "--skip-download", "--no-playlist"]
    add_deno_runtime_arg(args, request)
    add_access_args(args, request)
    args.extend(split_extra_args(request.extra_args))
    args.append(request.url.strip())
    return args


def build_download_command(request: DownloadRequest, attempt: int = 1, output_template: str = "", resolved_format: str = "") -> list[str]:
    validate_download_request(request)
    args = [str(YT_DLP_PATH), "--ignore-config", "--no-playlist", "--newline", "--no-simulate", "--part", "--progress", "--no-quiet", "--socket-timeout", str(request.socket_timeout), "--retries", "3", "--fragment-retries", "3", "--retry-sleep", "http:3", "--retry-sleep", "fragment:3"]
    # yt-dlp resumes matching .part files by default.  Keep this explicit so a
    # user's extra arguments cannot make the manager's option ambiguous.
    # Restart affects only the first invocation of a logical job. Automatic
    # attempts always preserve and continue its partial artifacts.
    if attempt > 1 or (request.resume_downloads and request.resume_policy != "restart"):
        args.append("--continue")
    else:
        args.append("--no-continue")
    add_deno_runtime_arg(args, request)
    add_access_args(args, request)
    add_download_mode_args(args, request)
    args.extend(["--print", "before_dl:__YTM_SELECTION__[%(format_id)j,%(requested_formats.:.format_id)j]"])
    add_section_args(args, request)

    if request.conflict_policy == "overwrite" and attempt == 1:
        args.append("--force-overwrites")
    if request.http_chunk_size:
        args.extend(["--http-chunk-size", request.http_chunk_size])

    download_dir = ensure_writable_directory(request.download_dir)
    args.extend(["-o", output_template or build_output_template(download_dir, request.filename_template)])
    args.extend(["--progress-template", "download:__YTM_PROGRESS__%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|%(info.format_id)s"])
    args.extend(["--print", "after_move:__YTM_RESULT__%(filepath)s"])
    args.extend(split_extra_args(request.extra_args))
    if resolved_format:
        args.extend(["-f", resolved_format])
    args.append(request.url.strip())
    return args


def positive_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def codec_state(item: dict, key: str) -> str:
    if key not in item:
        return "missing"
    value = item[key]
    if value is None:
        return "null"
    if isinstance(value, str):
        value = value.strip().lower()
        if not value:
            return "empty"
        if value == "none":
            return "absent"
        if value not in {"unknown", "?", "n/a", "na"}:
            return "known"
    return "unknown"


def classify_stream(item: dict) -> tuple[str, str]:
    """Combine explicit evidence; missing/unknown codecs never mean no stream."""
    evidence: dict[str, set[bool]] = {"video": set(), "audio": set()}
    for role, key in (("video", "vcodec"), ("audio", "acodec")):
        state = codec_state(item, key)
        if state in {"known", "absent"}:
            evidence[role].add(state == "known")
        ext_state = codec_state(item, role + "_ext")
        if ext_state in {"known", "absent"}:
            evidence[role].add(ext_state == "known")
    resolution = str(item.get("resolution") or "").strip().lower()
    if resolution in {"audio only", "video only"}:
        evidence["video"].add(resolution == "video only")
        evidence["audio"].add(resolution == "audio only")
    if positive_number(item.get("width")) or positive_number(item.get("height")):
        evidence["video"].add(True)
    if any(len(values) > 1 for values in evidence.values()):
        return "unknown", "conflicting_stream_evidence"
    video, audio = evidence["video"], evidence["audio"]
    if video == {True} and audio == {True}:
        return "muxed", "video_and_audio_present"
    if video == {True} and audio == {False}:
        return "video", "video_present_audio_absent"
    if video == {False} and audio == {True}:
        return "audio", "audio_present_video_absent"
    return "unknown", "insufficient_stream_evidence"


def format_bitrate(item: dict, kind: str) -> float | None:
    tbr, vbr, abr = (positive_number(item.get(key)) for key in ("tbr", "vbr", "abr"))
    if kind == "audio":
        return abr or tbr
    if kind == "video":
        return vbr or tbr
    if kind == "muxed":
        return tbr or (positive_number(vbr + abr) if vbr and abr else None)
    return None


def format_size(item: dict, duration: float | None, bitrate: float | None) -> tuple[int | None, str]:
    for key, source in (("filesize", "exact"), ("filesize_approx", "extractor_estimate")):
        value = positive_number(item.get(key))
        if value and int(value) > 0:
            return int(value), source
    if duration and bitrate:
        value = positive_number(duration * bitrate * 1000 / 8)
        if value and int(value) > 0:
            return int(value), "bitrate_estimate"
    return None, "unknown"


def parse_formats_metadata(raw_output: str) -> tuple[list[FormatItem], dict]:
    """Strictly parse --dump-single-json output into a URL-free public DTO."""
    try:
        metadata = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"yt-dlp вернул некорректные JSON-метаданные: {exc.msg}") from exc
    if not isinstance(metadata, dict) or not isinstance(metadata.get("formats"), list):
        raise ValueError("yt-dlp вернул метаданные без массива formats")
    result: list[FormatItem] = []
    for index, item in enumerate(metadata["formats"]):
        if not isinstance(item, dict):
            raise ValueError(f"Некорректный элемент formats[{index}]")
        format_id = item.get("format_id")
        if isinstance(format_id, bool) or not isinstance(format_id, (str, int)) or not str(format_id).strip():
            raise ValueError(f"В formats[{index}] отсутствует format_id")
        kind, reason = classify_stream(item)
        duration = positive_number(item.get("duration")) or positive_number(metadata.get("duration"))
        bitrate = format_bitrate(item, kind)
        size, source = format_size(item, duration, bitrate)
        result.append(FormatItem(
            format_id=str(format_id), extension=str(item.get("ext") or ""),
            resolution=str(item.get("resolution") or ""), fps=str(item.get("fps") or ""),
            video=str(item.get("vcodec") or ""), audio=str(item.get("acodec") or ""),
            size_bytes=size, size_source=source, duration=duration, bitrate=bitrate,
            note=str(item.get("format_note") or ""), audio_name=str(item.get("format") or item.get("format_note") or ""),
            protocol=str(item.get("protocol") or ""), language=str(item.get("language") or ""),
            dynamic_range=str(item.get("dynamic_range") or ""), kind=kind, kind_reason=reason,
            codec_states={key: codec_state(item, key) for key in ("vcodec", "acodec")},
            approximate=source not in {"exact", "unknown"}))
    diagnostic = {key: metadata.get(key) for key in ("id", "title", "extractor", "duration", "webpage_url_domain") if metadata.get(key) is not None}
    if "duration" in diagnostic:
        diagnostic["duration"] = positive_number(diagnostic["duration"])
    diagnostic["format_count"] = len(result)
    return result, diagnostic


def parse_formats(raw_output: str) -> list[FormatItem]:
    """Legacy -F parser retained only for explicit compatibility callers."""
    formats: list[FormatItem] = []
    for line in raw_output.splitlines():
        raw = line.rstrip()
        if not raw or raw.startswith("[") or raw.lower().startswith("id ") or raw.startswith("---"):
            continue
        columns = raw.split()
        if not columns:
            continue
        format_id = columns[0]
        if format_id.lower() in {"format", "id"}:
            continue
        extension = columns[1] if len(columns) > 1 else ""
        resolution = columns[2] if len(columns) > 2 else ""
        fps = ""
        for item in columns[3:8]:
            if item.endswith("fps") or item.isdigit() and item in {"24", "25", "30", "50", "60", "120"}:
                fps = item.replace("fps", "")
                break
        note = " ".join(columns[3:]) if len(columns) > 3 else ""
        video = "video" if "video" in raw.lower() or resolution not in {"audio", "audio-only"} else ""
        audio = "audio" if "audio" in raw.lower() else ""
        size_match = re.search(r"(?:~|≈)?\s*([\d.,]+)\s*(KiB|MiB|GiB|KB|MB|GB|B)", raw, re.IGNORECASE)
        size = f"{size_match.group(1)} {size_match.group(2)}" if size_match else ""
        size_bytes = 0
        if size_match:
            value = float(size_match.group(1).replace(",", "."))
            powers = {"b": 1, "kib": 1024, "mib": 1024**2, "gib": 1024**3, "kb": 1000, "mb": 1000**2, "gb": 1000**3}
            size_bytes = int(value * powers[size_match.group(2).lower()])
        formats.append(FormatItem(format_id=format_id, extension=extension, resolution=resolution, fps=fps, video=video, audio=audio, size=size, size_bytes=size_bytes, note=note, raw=raw))
    return formats


def quality_key(request: DownloadRequest) -> str:
    """Stable identity for resumable media requirements; deliberately excludes its name."""
    fmt = request.selected_format.strip() if request.download_mode == "manual" else request.download_mode
    if request.download_mode == "audio":
        fmt += f":{request.audio_format}"
    section = f":{request.section_start}-{request.section_end}" if request.section_enabled else ""
    return f"{fmt}{section}"


def find_result_file_from_logs(lines: list[str]) -> str:
    candidates: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if text.startswith(("[", "ERROR", "WARNING")):
            continue
        if any(text.lower().endswith(ext) for ext in (".mp4", ".m4a", ".mp3", ".opus", ".wav", ".webm", ".mkv", ".mov", ".avi")):
            candidates.append(text)
    for candidate in reversed(candidates):
        path = Path(candidate)
        if path.exists():
            return str(path)
    return candidates[-1] if candidates else ""


EXPLICIT_FORMAT = re.compile(r"[A-Za-z0-9_.-]+(?:\+[A-Za-z0-9_.-]+)?")


def explicit_format(value: str) -> bool:
    if not EXPLICIT_FORMAT.fullmatch(value):
        return False
    extensions = {"mp4", "m4a", "webm", "mkv", "mov", "mp3", "aac", "flac", "wav", "opus", "ogg", "oga", "mka", "m4v", "avi", "flv", "3gp", "3g2", "mpg", "mpeg", "ts", "m2ts", "aiff", "alac"}
    automatic = re.compile(r"(?:(?:best|worst)(?:video|audio)?|[bw](?:v|a)?)(?:\.\d+)?$", re.IGNORECASE)
    return all(part.lower() not in extensions | {"all", "mergeall"} and not automatic.fullmatch(part)
               for part in value.split("+"))


def result_parameters(request: DownloadRequest) -> dict:
    """Conservative identity: exclude only naming, UI and retry controls."""
    return request.model_dump(exclude={
        "last_url", "download_dir", "filename_template", "conflict_policy", "resume_policy",
        "resume_downloads", "auto_retry", "max_restarts", "socket_timeout", "http_chunk_size", "max_concurrent"})


def compatible_requests(old: DownloadRequest, new: DownloadRequest) -> bool:
    return (old.download_mode == new.download_mode == "manual"
            and explicit_format(old.selected_format) and explicit_format(new.selected_format)
            and not old.extra_args.strip() and not new.extra_args.strip()
            and result_parameters(old) == result_parameters(new))
