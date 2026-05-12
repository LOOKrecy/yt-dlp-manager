"""Safe subprocess management for yt-dlp jobs."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import IO, Iterable


class ProcessManager:
    """Track and control a single background download process."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()

    @property
    def running(self) -> bool:
        """Return whether a managed process is currently running."""

        with self._lock:
            return self._process is not None and self._process.poll() is None

    def start_download(self, command: list[str], log_path: Path) -> int:
        """Start a yt-dlp download command and stream stdout/stderr to a log file."""

        if not command:
            raise ValueError("Command must contain an executable")

        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("A download process is already running")

            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = log_path.open("a", encoding="utf-8")
            self._write_log_line(log_file, f"$ {self._format_command_for_log(command)}")

            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    shell=False,
                )
            except Exception:
                log_file.close()
                raise

            self._process = process

        stdout_thread = self._start_stream_reader(process.stdout, log_file, "stdout")
        stderr_thread = self._start_stream_reader(process.stderr, log_file, "stderr")
        self._start_exit_monitor(process, log_file, [stdout_thread, stderr_thread])
        return process.pid

    def stop_download(self) -> bool:
        """Stop the currently running download process, if there is one."""

        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                self._process = None
                return False

            process.terminate()
            return True

    def _start_stream_reader(
        self,
        stream: IO[str] | None,
        log_file: IO[str],
        stream_name: str,
    ) -> threading.Thread | None:
        """Read a process stream incrementally and append each line to the log."""

        if stream is None:
            return None

        thread = threading.Thread(
            target=self._stream_to_log,
            args=(stream, log_file, stream_name),
            daemon=True,
        )
        thread.start()
        return thread

    def _start_exit_monitor(
        self,
        process: subprocess.Popen[str],
        log_file: IO[str],
        stream_threads: list[threading.Thread | None],
    ) -> None:
        """Clear process state and close the log file after the command exits."""

        thread = threading.Thread(
            target=self._monitor_exit,
            args=(process, log_file, stream_threads),
            daemon=True,
        )
        thread.start()

    def _stream_to_log(self, stream: IO[str], log_file: IO[str], stream_name: str) -> None:
        for line in iter(stream.readline, ""):
            self._write_log_line(log_file, f"[{stream_name}] {line.rstrip()}")
        stream.close()

    def _monitor_exit(
        self,
        process: subprocess.Popen[str],
        log_file: IO[str],
        stream_threads: list[threading.Thread | None],
    ) -> None:
        return_code = process.wait()
        for thread in stream_threads:
            if thread is not None:
                thread.join()
        self._write_log_line(log_file, f"[process] exited with code {return_code}")

        with self._lock:
            if self._process is process:
                self._process = None

        log_file.close()

    def _write_log_line(self, log_file: IO[str], line: str) -> None:
        with self._lock:
            if log_file.closed:
                return
            log_file.write(f"{line}\n")
            log_file.flush()

    def _format_command_for_log(self, command: Iterable[str]) -> str:
        return " ".join(command)
