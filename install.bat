@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo  ClipCraft Setup ^& Dependency Installer
echo ========================================================
echo.

:: 1. Python virtual environment and dependencies
echo [1/2] Setting up Python virtual environment...
if not exist "%~dp0.venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 py -m venv .venv
  if errorlevel 1 python -m venv .venv
)

if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY_BIN=%~dp0.venv\Scripts\python.exe"
) else (
  set "PY_BIN=python"
)

"%PY_BIN%" -m pip install --upgrade pip
"%PY_BIN%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [Error] Dependency installation failed. Check your Python installation and internet connection.
  pause
  exit /b 1
)

:: 2. Check and verify FFmpeg
echo.
echo [2/2] Checking for FFmpeg...
where ffmpeg >nul 2>nul
if %errorlevel% equ 0 (
  echo [OK] FFmpeg found on system PATH.
) else (
  echo [Notice] FFmpeg was not detected on system PATH.
  echo Attempting automatic installation via winget...
  where winget >nul 2>nul
  if %errorlevel% equ 0 (
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    if %errorlevel% equ 0 (
      echo [OK] FFmpeg installed successfully via winget.
    ) else (
      echo [Warning] Automatic FFmpeg installation via winget failed or was cancelled.
      echo Please install FFmpeg manually from https://ffmpeg.org and add its bin folder to PATH.
    )
  ) else (
    echo [Warning] winget is not available on this system.
    echo Please install FFmpeg manually from https://ffmpeg.org and add its bin folder to PATH.
  )
)

echo.
echo ========================================================
echo  ClipCraft installed successfully!
echo  Run run_gui.bat to start the editor or run_batch.bat for batch rendering.
echo ========================================================
echo.
pause
