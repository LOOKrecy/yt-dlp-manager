from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Action = Literal["retry", "retry_429", "refresh_once", "user", "postprocess", "fatal", "manual", "stopped"]


@dataclass(frozen=True)
class Failure:
    code: str
    action: Action
    message: str
    retry_after: int | None = None


def classify_failure(stage: str, return_code: int | None, diagnostic_lines: list[str], stopped: bool = False) -> Failure:
    """Classify only the terminal diagnostic tail of one attempt."""
    if stopped:
        return Failure("stopped", "stopped", "Остановлено пользователем")
    text = "\n".join(diagnostic_lines[-40:]).lower()
    if stage == "postprocessing" or any(x in text for x in ("ffmpeg error", "ffprobe error")):
        return Failure("postprocess_failed", "postprocess", "Ошибка обработки ffmpeg/ffprobe; исходные дорожки сохранены")
    if re.search(r"http error 429|status(?: code)?[=: ]+429", text):
        match = re.search(r"retry-after\D{0,5}(\d+)", text)
        return Failure("http_429", "retry_429", "Сервер ограничил частоту запросов (HTTP 429)", max(60, int(match.group(1))) if match else 60)
    if re.search(r"http error (401|407)|login required|sign in|private video|deleted|geo(?:graphically)? restricted|\bdrm\b", text):
        return Failure("access_required", "user", "Требуется проверить доступ, cookies, proxy или ограничения видео")
    if re.search(r"requested format.*not available|format .*not available", text):
        return Failure("format_missing", "user", "Выбранный format_id исчез; обновите список и выберите формат заново")
    if re.search(r"no space left|disk full|permission denied|access is denied|invalid argument|not recognized|no such file.*(?:yt-dlp|ffmpeg|ffprobe)", text):
        return Failure("local_fatal", "fatal", "Локальная ошибка диска, доступа, executable или параметров")
    if stage == "downloading" and re.search(r"http error (403|410)", text):
        return Failure("cdn_expired", "refresh_once", "Ссылка потока отклонена (HTTP 403/410); требуется обновление метаданных")
    if re.search(r"http error 5\d\d|status(?: code)?[=: ]+5\d\d", text):
        return Failure("http_5xx", "retry", "Временная ошибка сервера")
    if re.search(r"timed? ?out|connection (?:reset|refused|aborted)|temporary failure in name resolution|name or service not known|getaddrinfo failed|network is unreachable", text):
        return Failure("network", "retry", "Соединение прервано или истекло время ожидания")
    return Failure("unknown", "manual", f"Неизвестная ошибка yt-dlp (код {return_code})")


def retry_delay(restart_number: int) -> int:
    return (5, 10, 20, 40, 60)[min(max(restart_number - 1, 0), 4)]
