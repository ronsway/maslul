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

REM vercel env/deploy commands only work from a directory linked to the Vercel
REM project (server\.vercel\project.json) - run everything from there, not
REM from wherever this script happened to be invoked.
pushd "%~dp0..\server"

echo Removing old GARTH_TOKEN from Vercel production (ok if it says "not found")...
call npx vercel env rm GARTH_TOKEN production --scope %SCOPE% --yes

echo.
echo Setting new GARTH_TOKEN...
call npx vercel env add GARTH_TOKEN production --scope %SCOPE% < "%TOKEN_FILE%"
if errorlevel 1 (
    echo Failed to set GARTH_TOKEN.
    popd
    pause
    exit /b 1
)

echo.
echo Redeploying backend...
call npx vercel deploy --prod --yes --scope %SCOPE%

popd

echo.
echo ===== Done =====
pause
endlocal
