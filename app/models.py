from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


DownloadMode = Literal["video", "video_only", "audio", "manual"]
AudioFormat = Literal["m4a", "mp3", "opus", "wav"]
FormatMode = Literal["auto", "manual"]
ConflictPolicy = Literal["ask", "rename", "overwrite"]
ResumePolicy = Literal["ask", "continue", "restart"]


class AppConfig(BaseModel):
    schema_version: int = 2
    last_url: str = ""
    download_dir: str = "Downloads"
    filename_template: str = ""
    proxy_enabled: bool = False
    proxy: str = ""
    cookies_enabled: bool = False
    cookies_file: str = ""
    section_enabled: bool = False
    section_keyframe_fix: bool = True
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
    resume_downloads: bool = True
    auto_retry: bool = True
    max_restarts: int = Field(default=5, ge=0, le=10)
    socket_timeout: int = Field(default=30, ge=1, le=600)
    http_chunk_size: str = ""
    max_concurrent: int = Field(default=2, ge=1, le=8)


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
    resume_policy: ResumePolicy = "ask"


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
    size_bytes: int = 0
    note: str = ""
    audio_name: str = ""
    raw: str = ""
    protocol: str = ""
    language: str = ""
    dynamic_range: str = ""
    kind: str = "unknown"
    approximate: bool = False


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
    filename_template: str = ""
    quality_key: str = ""
    schema_version: int = 2
    job_id: str = ""
    completed_at: str = ""
    size: int = 0
    reason: str = ""
    attempts: list[dict] = Field(default_factory=list)
    request_snapshot: dict = Field(default_factory=dict)
    incomplete: bool = False


class OpenPathRequest(BaseModel):
    path: str


class ToolActionRequest(BaseModel):
    action: Literal["yt-dlp-version", "ffmpeg-version", "deno-version", "yt-dlp-update", "project-check", "project-update"]
