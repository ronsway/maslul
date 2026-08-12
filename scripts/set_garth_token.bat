@echo off
setlocal

set "SCOPE=ron-lederers-projects"
set "TOKEN_FILE=%~dp0..\server\.env.garth_token"

if not exist "%TOKEN_FILE%" (
    echo No token file found at %TOKEN_FILE%
    echo Run generate_token.py first - it writes the token there automatically.
    pause
    exit /b 1
)

echo Removing old GARTH_TOKEN from Vercel production (ok if it says "not found")...
call npx vercel env rm GARTH_TOKEN production --scope %SCOPE% --yes

echo.
echo Setting new GARTH_TOKEN...
call npx vercel env add GARTH_TOKEN production --scope %SCOPE% < "%TOKEN_FILE%"
if errorlevel 1 (
    echo Failed to set GARTH_TOKEN.
    pause
    exit /b 1
)

echo.
echo Redeploying backend...
pushd "%~dp0..\server"
call npx vercel deploy --prod --yes --scope %SCOPE%
popd

echo.
echo ===== Done =====
pause
endlocal
