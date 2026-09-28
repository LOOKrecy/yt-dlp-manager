from __future__ import annotations

import shlex
from pathlib import Path
from app.models import DownloadRequest, FormatItem, FormatRequest
from app.path_utils import FFMPEG_PATH, FFPROBE_PATH, YT_DLP_PATH, build_output_template, ensure_writable_directory, find_deno_path, resolve_user_path

FALLBACK_IMPERSONATE_TARGETS = ["chrome", "chrome-110", "chrome-120", "edge", "safari", "firefox"]


def quote_command(args: list[str]) -> str:
    return " ".join(shlex.quote(str(arg)) for arg in args)


def split_extra_args(extra_args: str) -> list[str]:
    if not (extra_args or "").strip():
        return []
    try:
        return shlex.split(extra_args)
    except ValueError as exc:
        raise ValueError(f"Не удалось разобрать дополнительные параметры: {exc}") from exc


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
    args = [str(YT_DLP_PATH), "-F"]
    add_deno_runtime_arg(args, request)
    add_access_args(args, request)
    args.extend(split_extra_args(request.extra_args))
    args.append(request.url.strip())
    return args


def build_download_command(request: DownloadRequest) -> list[str]:
    validate_download_request(request)
    args = [str(YT_DLP_PATH)]
    add_deno_runtime_arg(args, request)
    add_access_args(args, request)
    add_download_mode_args(args, request)
    add_section_args(args, request)

    if request.conflict_policy == "overwrite":
        args.append("--force-overwrites")

    download_dir = ensure_writable_directory(request.download_dir)
    args.extend(["-o", build_output_template(download_dir, request.filename_template)])
    args.extend(["--print", "after_move:filepath"])
    args.extend(split_extra_args(request.extra_args))
    args.append(request.url.strip())
    return args


def parse_formats(raw_output: str) -> list[FormatItem]:
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
        size = next((item for item in columns if item.lower().endswith(("kib", "mib", "gib", "b"))), "")
        formats.append(FormatItem(format_id=format_id, extension=extension, resolution=resolution, fps=fps, video=video, audio=audio, size=size, note=note, raw=raw))
    return formats


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
