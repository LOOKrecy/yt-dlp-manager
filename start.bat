@echo off
set HOST=127.0.0.1
set PORT=8765
python -m uvicorn app.main:app --host %HOST% --port %PORT%
