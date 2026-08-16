@echo off
setlocal
cd /d "%~dp0.."

"%~dp0..\server\.venv\Scripts\python.exe" "%~dp0generate_token.py"

echo.
pause
endlocal
