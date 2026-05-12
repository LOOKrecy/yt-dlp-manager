# AGENTS.md

## Project

This project is a local Windows-only single-page web application for managing yt-dlp.exe through a browser UI.

The app is not a public web service. It must run only on localhost.

## Architecture

Use:

- Python 3.11+
- FastAPI
- Uvicorn
- Vanilla HTML/CSS/JavaScript
- JSON files for config and history
- subprocess with shell=False for running yt-dlp.exe

Do not use:

- Gradio
- React
- Vue
- Angular
- Docker
- Node.js build tools
- shell=True for user-controlled commands

## Security rules

Never build a shell command as one string.

Always run yt-dlp.exe with subprocess using a list of arguments.

User-provided extra arguments must be parsed safely and must never be passed through shell=True.

The server must bind to 127.0.0.1 only.

## Expected project layout

- app/main.py
- app/config_manager.py
- app/ytdlp_service.py
- app/process_manager.py
- app/history_manager.py
- app/path_utils.py
- app/static/index.html
- app/static/styles.css
- app/static/app.js
- bin/yt-dlp.exe
- bin/ffmpeg.exe
- bin/ffprobe.exe
- data/config.json
- data/history.json
- Downloads/
- logs/
- requirements.txt
- start.bat
- README.md

## Development style

Keep code simple and explicit.

Prefer small modules and clear functions.

Add type hints where useful.

Do not hide errors. Return clear error messages to the frontend.

## Verification

Before considering the task complete:

1. The app starts from start.bat.
2. The browser opens the local UI.
3. Config is saved and loaded.
4. Environment check detects yt-dlp.exe and ffmpeg.exe.
5. Format list can be requested with -F.
6. A selected format can be used for download.
7. Logs are visible in the UI.
8. Download can be stopped.
9. Download history is saved.
10. Result file can be opened or previewed when supported.
