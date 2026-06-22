@echo off
setlocal

cd /d "%~dp0BillNote_frontend"

if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8483"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=3015"
set "VITE_API_BASE_URL=http://127.0.0.1:%BACKEND_PORT%"
set "VITE_FRONTEND_PORT=%FRONTEND_PORT%"

if exist "node_modules\.bin\vite.CMD" (
  echo Waiting for backend on http://127.0.0.1:%BACKEND_PORT% ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=$env:BACKEND_PORT; $deadline=(Get-Date).AddSeconds(45); do { try { Invoke-RestMethod \"http://127.0.0.1:$port/api/deploy_status\" -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 1 } } while ((Get-Date) -lt $deadline); exit 1"
  if errorlevel 1 (
    echo Backend is not reachable on http://127.0.0.1:%BACKEND_PORT%.
    echo Please start backend first and keep the backend window open.
    pause
    exit /b 1
  )
  echo Starting frontend on http://127.0.0.1:%FRONTEND_PORT%
  echo Proxy target: %VITE_API_BASE_URL%
  node_modules\.bin\vite.CMD --host 0.0.0.0 --port %FRONTEND_PORT%
) else (
  echo Vite not found. Please install frontend dependencies first.
  pause
  exit /b 1
)

pause
