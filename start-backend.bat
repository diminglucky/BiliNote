@echo off
setlocal

cd /d "%~dp0backend"

set "PYTHON_EXE=D:\software\anaconda\envs\play\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Python not found: %PYTHON_EXE%
  pause
  exit /b 1
)

echo Starting backend on http://127.0.0.1:8483
echo Working directory: %cd%
"%PYTHON_EXE%" main.py

pause
