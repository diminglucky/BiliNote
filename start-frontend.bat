@echo off
setlocal

cd /d "%~dp0BillNote_frontend"

if exist "node_modules\.bin\vite.CMD" (
  echo Starting frontend on http://127.0.0.1:3015
  node_modules\.bin\vite.CMD --host 0.0.0.0 --port 3015
) else (
  echo Vite not found. Please install frontend dependencies first.
  pause
  exit /b 1
)

pause
