@echo off
rem Windows launcher: jb <command>  (same as ./jb on macOS/Linux)
set PYTHONUTF8=1
"%~dp0.venv\Scripts\python.exe" "%~dp0jobbot.py" %*
