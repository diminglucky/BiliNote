@echo off
setlocal

cd /d "%~dp0backend"

rem VideoNote uses its own proxy setting page or VIDEONOTE_PROXY_URL.
rem Clear generic proxy variables so stale IDE/system proxies cannot break downloads.
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="
set "VIDEONOTE_USE_ENV_PROXY="

set "PYTHON_EXE=D:\software\anaconda\envs\play\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Python not found: %PYTHON_EXE%
  pause
  exit /b 1
)

if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8483"

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort $env:BACKEND_PORT -State Listen -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
  echo Backend port %BACKEND_PORT% is already occupied.
  echo Close the old backend window, or run start-dev.bat to auto-pick a free port.
  pause
  exit /b 1
)

echo Starting backend on http://127.0.0.1:%BACKEND_PORT%
echo Browser entry: http://127.0.0.1:%BACKEND_PORT%
echo Runtime diagnostics: http://127.0.0.1:%BACKEND_PORT%/api/runtime_diagnostics
echo Working directory: %cd%
"%PYTHON_EXE%" main.py

pause
