"""Service layer placeholder for yt-dlp integration."""

from app.models import DownloadRequest
from app.process_manager import ProcessManager


class YtDlpService:
    """Minimal service facade for future download handling."""

    def __init__(self, process_manager: ProcessManager) -> None:
        self._process_manager = process_manager

    def prepare_download(self, request: DownloadRequest) -> dict[str, str]:
        """Validate and acknowledge a download request without starting yt-dlp yet."""

        return {"status": "queued", "url": request.url}
