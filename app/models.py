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
    """Minimal request model for future download jobs."""

    url: str = Field(..., min_length=1)
