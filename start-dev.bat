@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=D:\software\anaconda\envs\play\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Python not found: %PYTHON_EXE%
  pause
  exit /b 1
)

echo Starting BiliNote backend on http://127.0.0.1:8483 ...
start "BiliNote Backend" "%~dp0start-backend.bat"

echo Starting BiliNote frontend on http://127.0.0.1:3015 ...
start "BiliNote Frontend" "%~dp0start-frontend.bat"

echo.
echo Open http://127.0.0.1:3015 after both windows finish starting.
echo Keep the backend window open while using the browser version.
pause
