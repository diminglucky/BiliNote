@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=D:\software\anaconda\envs\play\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Python not found: %PYTHON_EXE%
  pause
  exit /b 1
)

for /f %%p in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=8483; while (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) { $p++ }; Write-Output $p"') do set "BACKEND_PORT=%%p"
for /f %%p in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=3015; while (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) { $p++ }; Write-Output $p"') do set "FRONTEND_PORT=%%p"

if not "%BACKEND_PORT%"=="8483" (
  echo Port 8483 is already occupied. Using backend port %BACKEND_PORT% for this run.
)
if not "%FRONTEND_PORT%"=="3015" (
  echo Port 3015 is already occupied. Using frontend port %FRONTEND_PORT% for this run.
)

echo Starting VideoNote backend on http://127.0.0.1:%BACKEND_PORT% ...
start "VideoNote Backend" "%~dp0start-backend.bat"

echo Waiting for backend to become reachable ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=$env:BACKEND_PORT; $deadline=(Get-Date).AddSeconds(45); do { try { Invoke-RestMethod \"http://127.0.0.1:$port/api/deploy_status\" -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 1 } } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo Backend did not become reachable on http://127.0.0.1:%BACKEND_PORT%.
  echo Check the backend window for errors.
  pause
  exit /b 1
)

echo Starting VideoNote frontend on http://127.0.0.1:%FRONTEND_PORT% ...
start "VideoNote Frontend" "%~dp0start-frontend.bat"

echo.
echo Open http://127.0.0.1:%FRONTEND_PORT% after both windows finish starting.
echo Backend API: http://127.0.0.1:%BACKEND_PORT%
echo Keep the backend window open while using the browser version.
pause
