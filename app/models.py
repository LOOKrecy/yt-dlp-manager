"""Pydantic models used by the yt-dlp manager API."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Runtime configuration exposed by the local application."""

    host: str = "127.0.0.1"
    port: int = 8765
    downloads_dir: Path = Field(default=Path("Downloads"))
    data_dir: Path = Field(default=Path("data"))
    logs_dir: Path = Field(default=Path("logs"))


class HealthResponse(BaseModel):
    """Simple health-check response."""

    status: str = "ok"
    service: str = "yt-dlp-manager"


class StoredConfig(BaseModel):
    """Persisted UI configuration values."""

    last_url: str = ""
    download_dir: str = "Downloads"
    proxy_enabled: bool = False
    proxy_url: str = ""
    cookies_enabled: bool = False
    cookies_file: str = ""
    section_enabled: bool = False
    section_start: str = ""
    section_end: str = ""
    impersonate_enabled: bool = False
    impersonate_target: str = ""
    download_mode: str = "video"
    audio_format: str = "mp3"
    format_mode: str = "best"
    selected_format: str = ""
    extra_args: str = ""
    embed_metadata: bool = True
    embed_thumbnail: bool = False
    write_subtitles: bool = False
    write_auto_subtitles: bool = False
    subtitles_language: str = ""
    playlist_enabled: bool = False
    playlist_start: str = ""
    playlist_end: str = ""
    overwrite_files: bool = False
    restrict_filenames: bool = False
    output_template: str = "%(title)s.%(ext)s"


class ConfigResponse(StoredConfig):
    """Configuration response returned to the frontend."""


class ConfigUpdateRequest(StoredConfig):
    """Configuration payload accepted from the frontend."""


class EnvironmentItem(BaseModel):
    """Status information for a required local path."""

    name: str
    kind: Literal["directory", "file"]
    path: str
    exists: bool


class EnvironmentResponse(BaseModel):
    """Grouped status information for required app paths."""

    directories: dict[str, EnvironmentItem]
    tools: dict[str, EnvironmentItem]


class DownloadRequest(BaseModel):
    """Request model for yt-dlp format lookups and download jobs."""

    url: str = Field(..., min_length=1)
    proxy_enabled: bool = False
    proxy_url: str = ""
    cookies_enabled: bool = False
    cookies_file: str = ""
    section_enabled: bool = False
    section_start: str = ""
    section_end: str = ""
    impersonate_enabled: bool = False
    impersonate_target: str = ""
    download_mode: str = "video"
    audio_format: str = "mp3"
    format_mode: str = "best"
    selected_format: str = ""
    extra_args: str = ""
    embed_metadata: bool = True
    embed_thumbnail: bool = False
    write_subtitles: bool = False
    write_auto_subtitles: bool = False
    subtitles_language: str = ""
    playlist_enabled: bool = False
    playlist_start: str = ""
    playlist_end: str = ""
    overwrite_files: bool = False
    restrict_filenames: bool = False
    output_template: str = "%(title)s.%(ext)s"
    download_dir: str = "Downloads"


class FormatRequest(DownloadRequest):
    """Request model for loading available yt-dlp formats."""


class FormatResponse(BaseModel):
    """Raw yt-dlp format-listing command output."""

    status: Literal["ok"] = "ok"
    command: list[str]
    output: str


class DownloadResponse(BaseModel):
    """Response returned after a download process is started."""

    status: Literal["started"] = "started"
    url: str
    pid: int
    log_path: str


class StopDownloadResponse(BaseModel):
    """Response returned when stopping an active download."""

    status: Literal["stopped", "idle"]


class LogResponse(BaseModel):
    """Polling response with recent download log lines."""

    log_path: str = ""
    running: bool = False
    lines: list[str] = Field(default_factory=list)


class HistoryItem(BaseModel):
    """Stored download history entry."""

    id: str
    url: str
    status: str
    created_at: str
    log_path: str = ""
    pid: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HistoryResponse(BaseModel):
    """List of stored download history entries."""

    items: list[HistoryItem]


class ClearHistoryResponse(BaseModel):
    """Response returned after history cleanup."""

    status: Literal["cleared"] = "cleared"
    deleted: int


class OpenPathRequest(BaseModel):
    """Request to open a local file or directory on the host system."""

    path: str = Field(..., min_length=1)


class OpenPathResponse(BaseModel):
    """Response returned after dispatching a local file-manager command."""

    status: Literal["opened"] = "opened"
    path: str
