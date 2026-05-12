# yt-dlp Manager

Минимальный локальный FastAPI-проект для будущего управления загрузками через `yt-dlp`.

## Структура

- `app/main.py` — точка входа FastAPI, API и раздача статического frontend.
- `app/static/` — минимальный HTML/CSS/JS интерфейс.
- `Downloads/`, `data/`, `logs/` — локальные runtime-директории.
- `bin/` — место для вспомогательных исполняемых файлов.

## Запуск

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

На Windows можно запустить:

```bat
start.bat
```

Приложение намеренно слушает только `127.0.0.1:8765`.
