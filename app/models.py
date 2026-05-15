from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


DownloadMode = Literal["video", "video_only", "audio", "manual"]
AudioFormat = Literal["m4a", "mp3", "opus", "wav"]
FormatMode = Literal["auto", "manual"]
ConflictPolicy = Literal["ask", "rename", "overwrite"]


class AppConfig(BaseModel):
    last_url: str = ""
    download_dir: str = "Downloads"
    filename_template: str = ""
    proxy_enabled: bool = False
    proxy: str = ""
    cookies_enabled: bool = False
    cookies_file: str = ""
    section_enabled: bool = False
    section_start: str = "00:00:00"
    section_end: str = "00:00:00"
    impersonate_enabled: bool = False
    impersonate_target: str = ""
    deno_enabled: bool = False
    download_mode: DownloadMode = "video"
    audio_format: AudioFormat = "m4a"
    format_mode: FormatMode = "auto"
    selected_format: str = ""
    extra_args: str = ""


class FormatRequest(BaseModel):
    url: str = ""
    proxy_enabled: bool = False
    proxy: str = ""
    cookies_enabled: bool = False
    cookies_file: str = ""
    impersonate_enabled: bool = False
    impersonate_target: str = ""
    deno_enabled: bool = False
    extra_args: str = ""


class DownloadRequest(AppConfig):
    url: str = Field(default="")
    conflict_policy: ConflictPolicy = "ask"


class OutputConflictRequest(DownloadRequest):
    pass


class FormatItem(BaseModel):
    format_id: str
    extension: str = ""
    resolution: str = ""
    fps: str = ""
    video: str = ""
    audio: str = ""
    size: str = ""
    note: str = ""
    raw: str


class HistoryEntry(BaseModel):
    id: str
    datetime: str
    url: str
    title: str = ""
    download_dir: str
    output_file: str = ""
    mode: str
    format: str = ""
    status: str
    error: str = ""


class OpenPathRequest(BaseModel):
    path: str


class ToolActionRequest(BaseModel):
    action: Literal["yt-dlp-version", "ffmpeg-version", "deno-version", "yt-dlp-update"]
