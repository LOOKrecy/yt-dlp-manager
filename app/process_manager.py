"""Process management placeholder for future yt-dlp jobs."""


class ProcessManager:
    """Track whether a background download process is active."""

    def __init__(self) -> None:
        self._running = False

    @property
    def running(self) -> bool:
        """Return whether a managed process is currently running."""

        return self._running
