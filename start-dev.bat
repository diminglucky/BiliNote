@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=D:\software\anaconda\envs\play\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Python not found: %PYTHON_EXE%
  pause
  exit /b 1
)

echo Starting VideoNote backend on http://127.0.0.1:8483 ...
start "VideoNote Backend" "%~dp0start-backend.bat"

echo Waiting for backend to become reachable ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(45); do { try { Invoke-RestMethod 'http://127.0.0.1:8483/api/deploy_status' -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 1 } } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo Backend did not become reachable on http://127.0.0.1:8483.
  echo Check the backend window for errors.
  pause
  exit /b 1
)

echo Starting VideoNote frontend on http://127.0.0.1:3015 ...
start "VideoNote Frontend" "%~dp0start-frontend.bat"

echo.
echo Open http://127.0.0.1:3015 after both windows finish starting.
echo Keep the backend window open while using the browser version.
pause
