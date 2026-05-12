"""HTTP API for yt-dlp-manager."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.config_manager import load_config, save_config

app = FastAPI(title="yt-dlp-manager")


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    """Return the current application configuration."""
    return load_config()


@app.post("/api/config")
def update_config(config: dict[str, Any]) -> dict[str, Any]:
    """Persist and return the updated application configuration."""
    return save_config(config)
