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

echo This will delete and recreate only the local virtual environment: %CD%\%VENV_DIR%
if exist "%VENV_DIR%\" (
  rmdir /s /q "%VENV_DIR%"
  if errorlevel 1 (
    echo ERROR: Failed to delete %CD%\%VENV_DIR%.
    echo Close any running application windows or terminals that may be using it, then try again.
    pause
    popd >nul 2>&1
    exit /b 1
  )
)

python --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python was not found. Install Python 3.11 or newer and ensure python.exe is available on PATH.
  echo No dependencies were installed.
  pause
  popd >nul 2>&1
  exit /b 1
)

echo Creating local virtual environment in %CD%\%VENV_DIR% ...
python -m venv "%VENV_DIR%"
if errorlevel 1 (
  echo ERROR: Failed to create the local virtual environment at %CD%\%VENV_DIR%.
  echo No global Python installation was modified.
  pause
  popd >nul 2>&1
  exit /b 1
)

if not exist "%VENV_PYTHON%" (
  echo ERROR: Local virtual environment Python was not found after creation: %CD%\%VENV_PYTHON%
  pause
  popd >nul 2>&1
  exit /b 1
)

if not exist "%VENV_PIP%" (
  echo ERROR: Local virtual environment pip was not found after creation: %CD%\%VENV_PIP%
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

echo Local virtual environment was reset successfully.
echo Launch the application with start.bat.
pause
popd >nul 2>&1
exit /b 0
