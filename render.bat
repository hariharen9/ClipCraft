@echo off
setlocal
cd /d "%~dp0"

:: Prefer the local virtual environment Python if available
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_BIN=%~dp0.venv\Scripts\python.exe"
) else if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    set "PY_BIN=python"
) else (
    set "PY_BIN=python"
)

"%PY_BIN%" clipcraft.py %*
if errorlevel 1 (
    echo.
    echo ========================================================
    echo  ClipCraft encountered an error (exit code %errorlevel%).
    echo ========================================================
    echo.
    pause
)

