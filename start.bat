@echo off
setlocal

rem Resolve the project root to the directory that contains this script.
set "PROJECT_ROOT=%~dp0"
pushd "%PROJECT_ROOT%" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Could not change to the project directory: %PROJECT_ROOT%
  pause
  exit /b 1
)

set "VENV_DIR=.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"
set "APP_URL=http://127.0.0.1:8765"

if not exist "%VENV_DIR%\" (
  echo Creating local virtual environment in %CD%\%VENV_DIR% ...
  python --version >nul 2>&1
  if errorlevel 1 (
    echo ERROR: Python was not found. Install Python 3.11 or newer and ensure python.exe is available on PATH.
    echo No dependencies were installed.
    pause
    popd >nul 2>&1
    exit /b 1
  )

  python -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo ERROR: Failed to create the local virtual environment at %CD%\%VENV_DIR%.
    echo No global Python installation was modified.
    pause
    popd >nul 2>&1
    exit /b 1
  )
)

if not exist "%VENV_PYTHON%" (
  echo ERROR: Local virtual environment Python was not found: %CD%\%VENV_PYTHON%
  echo Delete .venv and run start.bat again, or run reset_venv.bat to recreate it.
  pause
  popd >nul 2>&1
  exit /b 1
)

if not exist "%VENV_PIP%" (
  echo ERROR: Local virtual environment pip was not found: %CD%\%VENV_PIP%
  echo Delete .venv and run start.bat again, or run reset_venv.bat to recreate it.
  pause
  popd >nul 2>&1
  exit /b 1
)

echo Upgrading pip inside the local virtual environment only...
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
  echo ERROR: Failed to upgrade pip inside %CD%\%VENV_DIR%.
  echo No global Python installation was modified.
  pause
  popd >nul 2>&1
  exit /b 1
)

echo Installing requirements inside the local virtual environment only...
"%VENV_PIP%" install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Failed to install requirements into %CD%\%VENV_DIR%.
  echo No global Python installation was modified.
  pause
  popd >nul 2>&1
  exit /b 1
)

if exist "bin\yt-dlp.exe" (
  echo Checking for yt-dlp updates...
  "bin\yt-dlp.exe" -U
  if errorlevel 1 echo WARNING: yt-dlp update check failed; starting with the installed version.
)

echo Opening %APP_URL% ...
start "" "%APP_URL%"

echo Starting Local yt-dlp Manager with %CD%\%VENV_PYTHON% ...
"%VENV_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8765
if errorlevel 1 (
  echo ERROR: Backend failed to start or exited with an error.
  pause
  popd >nul 2>&1
  exit /b 1
)

popd >nul 2>&1
exit /b 0
