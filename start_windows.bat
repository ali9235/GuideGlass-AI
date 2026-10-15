@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" server.py %*
  pause
  exit /b
)
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 server.py %*
) else (
  where python >nul 2>&1
  if %errorlevel%==0 (
    python server.py %*
  ) else (
    echo Python is not installed. Install Python 3 from https://www.python.org/downloads/windows/
    echo Then run this file again.
  )
)
pause
