# AGENTS.md

## Project rules

- Keep the application localhost-only unless the user explicitly requests otherwise.
- The backend must be a FastAPI application.
- The backend must bind to `127.0.0.1:8765` by default.
- The frontend must use Vanilla JS; do not add React, Vue, Angular, or other frontend frameworks.
- Persist application configuration and download history as local JSON files.
- Runtime files belong in `Downloads/`, `data/`, and `logs/`.
- Do not add or require Gradio.
- Do not add or require Docker.
- Do not add or require Node.js.
- Do not use `shell=True` for commands that include user-provided input or user-configurable arguments.
