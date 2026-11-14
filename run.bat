@echo off
cd /d "%~dp0"
echo Starting BugFlow at http://localhost:8080
where py >nul 2>nul
if not errorlevel 1 (
  py -3 server.py
  goto :end
)
where python >nul 2>nul
if not errorlevel 1 (
  python server.py
  goto :end
)
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" server.py
  goto :end
)
echo Python 3 was not found. Install Python 3.10 or newer, then run this file again.
pause
:end
pause
