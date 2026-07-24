@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "VENV_PY=%PROJECT_DIR%server\.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo Backend virtual environment not found at:
    echo   %VENV_PY%
    echo Create it first:
    echo   cd "%PROJECT_DIR%server"
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt uvicorn
    pause
    exit /b 1
)

echo Starting Maslul backend on http://localhost:8000 ...
start "Maslul Backend" cmd /k ""%VENV_PY%" -m uvicorn api.index:app --reload --port 8000 --app-dir "%PROJECT_DIR%server""

echo Starting Maslul web on http://localhost:8080 ...
start "Maslul Web" cmd /k ""%VENV_PY%" -m http.server 8080 --directory "%PROJECT_DIR%web""

timeout /t 2 /nobreak >nul
start "" "http://localhost:8080"

echo.
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:8080
echo Two windows opened - closing them stops the servers.
endlocal
