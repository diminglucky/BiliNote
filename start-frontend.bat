@echo off
setlocal

cd /d "%~dp0BillNote_frontend"

if exist "node_modules\.bin\vite.CMD" (
  echo Waiting for backend on http://127.0.0.1:8483 ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(45); do { try { Invoke-RestMethod 'http://127.0.0.1:8483/api/deploy_status' -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 1 } } while ((Get-Date) -lt $deadline); exit 1"
  if errorlevel 1 (
    echo Backend is not reachable on http://127.0.0.1:8483.
    echo Please start backend first and keep the backend window open.
    pause
    exit /b 1
  )
  echo Starting frontend on http://127.0.0.1:3015
  node_modules\.bin\vite.CMD --host 0.0.0.0 --port 3015
) else (
  echo Vite not found. Please install frontend dependencies first.
  pause
  exit /b 1
)

pause
