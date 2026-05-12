"""Service layer for building and running yt-dlp commands."""

from __future__ import annotations

import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import DownloadRequest
from app.path_utils import DOWNLOADS_DIR, LOGS_DIR, REQUIRED_TOOLS, ROOT_DIR
from app.process_manager import ProcessManager


class YtDlpService:
    """Build safe yt-dlp argument lists and delegate execution."""

    def __init__(self, process_manager: ProcessManager) -> None:
        self._process_manager = process_manager
        self._executable = REQUIRED_TOOLS["yt-dlp"]

    def prepare_download(self, request: DownloadRequest) -> dict[str, str]:
        """Validate, build, and start a yt-dlp download command."""

        command = self.build_download_command(request)
        log_path = self._next_log_path()
        pid = self._process_manager.start_download(command, log_path)

        return {
            "status": "started",
            "url": self._value(request, "url"),
            "pid": str(pid),
            "log_path": str(log_path),
        }

    def stop_download(self) -> dict[str, str]:
        """Stop the active download process."""

        stopped = self._process_manager.stop_download()
        return {"status": "stopped" if stopped else "idle"}

    def build_format_request_command(self, request: DownloadRequest) -> list[str]:
        """Build `yt-dlp.exe -F <URL>` with network/access and extra arguments."""

        self._validate_request(request)
        return [
            str(self._executable),
            "-F",
            self._value(request, "url"),
            *self._network_access_args(request),
            *self._extra_args(request),
        ]

    def build_download_command(self, request: DownloadRequest) -> list[str]:
        """Build a download command with deterministic argument group ordering."""

        self._validate_request(request)
        return [
            str(self._executable),
            *self._network_access_args(request),
            *self._format_args(request),
            *self._section_args(request),
            *self._output_args(request),
            *self._extra_args(request),
            self._value(request, "url"),
        ]

    def _validate_request(self, request: DownloadRequest) -> None:
        url = self._value(request, "url")
        if not url:
            raise ValueError("URL is required")

        if self._bool_value(request, "proxy_enabled") and not self._value(
            request,
            "proxy_url",
        ):
            raise ValueError("Proxy URL is required when proxy is enabled")

        if self._bool_value(request, "cookies_enabled"):
            cookies_file = self._value(request, "cookies_file")
            if not cookies_file:
                raise ValueError("Cookies file is required when cookies are enabled")
            if not self._resolve_existing_path(cookies_file).is_file():
                raise ValueError("Cookies file must exist when cookies are enabled")

        if self._bool_value(request, "impersonate_enabled") and not self._value(
            request,
            "impersonate_target",
        ):
            raise ValueError("Impersonate target is required when impersonation is enabled")

        self._extra_args(request)

    def _network_access_args(self, request: DownloadRequest) -> list[str]:
        args: list[str] = []

        if self._bool_value(request, "proxy_enabled"):
            args.extend(["--proxy", self._value(request, "proxy_url")])

        if self._bool_value(request, "cookies_enabled"):
            args.extend(
                [
                    "--cookies",
                    str(self._resolve_existing_path(self._value(request, "cookies_file"))),
                ]
            )

        if self._bool_value(request, "impersonate_enabled"):
            args.extend(["--impersonate", self._value(request, "impersonate_target")])

        return args

    def _format_args(self, request: DownloadRequest) -> list[str]:
        args: list[str] = []
        download_mode = self._value(request, "download_mode", "video")
        format_mode = self._value(request, "format_mode", "best")
        selected_format = self._value(request, "selected_format")

        if download_mode == "audio":
            args.extend(
                [
                    "--extract-audio",
                    "--audio-format",
                    self._value(request, "audio_format", "mp3"),
                ]
            )
        elif download_mode == "video_audio":
            args.extend(["-f", selected_format or "bestvideo+bestaudio/best"])
        elif selected_format:
            args.extend(["-f", selected_format])
        elif format_mode == "best":
            args.extend(["-f", "best"])
        elif format_mode == "worst":
            args.extend(["-f", "worst"])

        if self._bool_value(request, "embed_metadata"):
            args.append("--embed-metadata")
        if self._bool_value(request, "embed_thumbnail"):
            args.append("--embed-thumbnail")
        if self._bool_value(request, "write_subtitles"):
            args.append("--write-subs")
        if self._bool_value(request, "write_auto_subtitles"):
            args.append("--write-auto-subs")

        subtitles_language = self._value(request, "subtitles_language")
        if subtitles_language:
            args.extend(["--sub-langs", subtitles_language])

        return args

    def _section_args(self, request: DownloadRequest) -> list[str]:
        args: list[str] = []

        if self._bool_value(request, "section_enabled"):
            start = self._value(request, "section_start")
            end = self._value(request, "section_end")
            if start or end:
                args.extend(["--download-sections", f"*{start}-{end}"])

        if self._bool_value(request, "playlist_enabled"):
            playlist_start = self._value(request, "playlist_start")
            playlist_end = self._value(request, "playlist_end")
            if playlist_start:
                args.extend(["--playlist-start", playlist_start])
            if playlist_end:
                args.extend(["--playlist-end", playlist_end])
        else:
            args.append("--no-playlist")

        return args

    def _output_args(self, request: DownloadRequest) -> list[str]:
        args: list[str] = []
        download_dir = self._resolve_output_dir(self._value(request, "download_dir"))
        output_template = self._value(request, "output_template", "%(title)s.%(ext)s")

        args.extend(["-P", str(download_dir), "-o", output_template])

        if self._bool_value(request, "overwrite_files"):
            args.append("--force-overwrites")
        if self._bool_value(request, "restrict_filenames"):
            args.append("--restrict-filenames")

        return args

    def _extra_args(self, request: DownloadRequest) -> list[str]:
        extra_args = self._value(request, "extra_args")
        if not extra_args:
            return []
        return shlex.split(extra_args)

    def _value(self, request: DownloadRequest, field_name: str, default: str = "") -> str:
        value = self._raw_value(request, field_name, default)
        return str(value).strip() if value is not None else ""

    def _bool_value(self, request: DownloadRequest, field_name: str) -> bool:
        value = self._raw_value(request, field_name, False)
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _raw_value(self, request: DownloadRequest, field_name: str, default: Any) -> Any:
        if hasattr(request, field_name):
            return getattr(request, field_name)
        if (
            hasattr(request, "model_extra")
            and request.model_extra
            and field_name in request.model_extra
        ):
            return request.model_extra[field_name]
        return default

    def _resolve_existing_path(self, path_value: str) -> Path:
        path = Path(path_value).expanduser()
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path

    def _resolve_output_dir(self, path_value: str) -> Path:
        if not path_value:
            return DOWNLOADS_DIR

        path = Path(path_value).expanduser()
        if not path.is_absolute():
            path = ROOT_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _next_log_path(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return LOGS_DIR / f"download-{timestamp}.log"
