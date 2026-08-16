@echo off
setlocal enabledelayedexpansion

set "SCOPE=ron-lederers-projects"
set "PROJECT_DIR=%~dp0"

set "MSG=%*"
if "%MSG%"=="" set "MSG=Deploy"

echo ===== Maslul deploy to Vercel (%SCOPE%) =====
echo.

echo --- Bumping version ---
for /f "delims=" %%v in ('node "%PROJECT_DIR%scripts\bump_version.js" %MSG%') do set "NEWVER=%%v"
if "%NEWVER%"=="" (
    echo Version bump failed - is Node.js installed and on PATH?
    pause
    exit /b 1
)
echo New version: %NEWVER%

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
echo --- Committing version bump ---
pushd "%PROJECT_DIR%"
git add VERSION CHANGELOG.md web\version.js web\sw.js
git commit -m "Release v%NEWVER%: %MSG%"
git push origin master
popd

echo.
echo ===== Done: v%NEWVER% =====
echo Backend:  https://maslul-backend.vercel.app
echo Frontend: https://maslul-web.vercel.app
pause
endlocal
