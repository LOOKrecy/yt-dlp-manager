@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

start "" "http://127.0.0.1:8765"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
