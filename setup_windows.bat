@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" tools\prepare_assets.py --models --web
if errorlevel 1 goto failed
echo Setup complete. Run start_windows.bat.
pause
exit /b 0
:failed
echo Setup failed. See the error above. Python 3.12 is required.
pause
exit /b 1
