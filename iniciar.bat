@echo off
cd /d "%~dp0"
if exist "dist\SysPulse\SysPulse.exe" (
    start "" "dist\SysPulse\SysPulse.exe"
    exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "main.py"
    exit /b
)
echo Abra a versao portatil ou prepare o ambiente conforme o README.
pause
