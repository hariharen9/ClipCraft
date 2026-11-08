@echo off
setlocal
cd /d "%~dp0"

echo ========================================================================
echo  ClipCraft - Standalone Portable Windows Build Launcher
echo ========================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment (.venv) was not found.
    echo Run install.bat first to set up dependencies.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" build_portable.py
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. See messages above.
    pause
    exit /b 1
)

echo.
echo ========================================================================
echo  Build finished successfully! Check the 'dist\ClipCraft' folder.
echo ========================================================================
pause

