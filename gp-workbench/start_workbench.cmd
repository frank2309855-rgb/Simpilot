@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 local_app.py %*
) else (
  python -X utf8 local_app.py %*
)
if errorlevel 1 (
  echo Start failed. Follow README.md to create .venv and install requirements.txt.
  pause
)
endlocal
