@echo off
setlocal
cd /d "%~dp0.."

echo ===== Step 1/2: Generate a fresh Garmin token =====
echo You will be asked for your Garmin email/password (and an MFA code if Garmin prompts for one).
echo.
"%~dp0..\server\.venv\Scripts\python.exe" "%~dp0generate_token.py"
if errorlevel 1 (
    echo.
    echo Token generation failed - aborting before touching Vercel.
    pause
    exit /b 1
)

echo.
echo ===== Step 2/2: Push token to Vercel and redeploy backend =====
call "%~dp0set_garth_token.bat"

endlocal
