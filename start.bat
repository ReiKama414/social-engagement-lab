@echo off
chcp 65001 > nul
title Social Engagement Automation Lab Launcher
cd /d "%~dp0"

echo ========================================================
echo   Social Engagement Automation Lab Launcher
echo   [1/3] Starting Backend Server (FastAPI + SQLite)...
echo ========================================================
start "Social Lab Backend" "%~dp0run_backend.bat"

echo.
echo   [2/3] Starting Frontend Server (Next.js)...
start "Social Lab Frontend" "%~dp0run_frontend.bat"

echo.
echo   [3/3] Waiting for servers to initialize...
timeout /t 3 /nobreak > nul

echo.
echo   Opening browser at http://localhost:3000 ...
start http://localhost:3000

echo.
echo ========================================================
echo   [SUCCESS] All systems launched successfully!
echo   - Frontend: http://localhost:3000
echo   - Backend:  http://127.0.0.1:8000
echo   - Mock UI:  http://127.0.0.1:8000/mock-social
echo ========================================================
echo   You may minimize this window.
pause
