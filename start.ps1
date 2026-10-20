# Social Engagement Automation Lab Launcher for Windows PowerShell
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   Social Engagement Automation Lab (社群實驗室)" -ForegroundColor Magenta
Write-Host "   - Backend:  http://127.0.0.1:8000" -ForegroundColor Yellow
Write-Host "   - Frontend: http://localhost:3000" -ForegroundColor Yellow
Write-Host "   - Mock UI:  http://127.0.0.1:8000/mock-social" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan

$root = $PSScriptRoot

Write-Host "`n[1/3] Starting Backend Server (FastAPI)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; .\venv\Scripts\Activate.ps1; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

Write-Host "[2/3] Starting Frontend Server (Next.js)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"

Write-Host "[3/3] Waiting for servers to initialize..." -ForegroundColor Cyan
Start-Sleep -Seconds 3

Write-Host "`n✓ Opening default browser to http://localhost:3000 ..." -ForegroundColor Green
Start-Process "http://localhost:3000"

