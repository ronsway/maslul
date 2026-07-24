@echo off
setlocal

set "SCOPE=ron-lederers-projects"
set "PROJECT_DIR=%~dp0"

echo ===== Maslul deploy to Vercel (%SCOPE%) =====
echo.

echo --- Backend (maslul-backend) ---
pushd "%PROJECT_DIR%server"
call npx vercel deploy --prod --yes --scope %SCOPE%
if errorlevel 1 (
    echo Backend deploy failed.
    popd
    pause
    exit /b 1
)
popd

echo.
echo --- Frontend (maslul-web) ---
pushd "%PROJECT_DIR%web"
call npx vercel deploy --prod --yes --scope %SCOPE%
if errorlevel 1 (
    echo Frontend deploy failed.
    popd
    pause
    exit /b 1
)
popd

echo.
echo ===== Done =====
echo Backend:  https://maslul-backend.vercel.app
echo Frontend: https://maslul-web.vercel.app
pause
endlocal
