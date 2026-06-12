@echo off
cd /d "%~dp0backend"
"D:\software\anaconda\envs\play\python.exe" main.py >> backend-task.out.log 2>> backend-task.err.log
