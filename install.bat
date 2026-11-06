@echo off
setlocal
cd /d "%~dp0"
py -3.11 -m venv .venv
if errorlevel 1 py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Dependency installation failed. Check your Python installation and internet connection.
  pause
  exit /b 1
)
echo.
echo ClipCraft installed. Use run_gui.bat or render.bat.
pause
