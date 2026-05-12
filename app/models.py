"""Pydantic models used by the yt-dlp manager API."""

from pathlib import Path

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
