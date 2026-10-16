@echo off
setlocal
cd /d "%~dp0"
set "AGENTGUARD_PORT=8912"
set "AGENTGUARD_URL=http://127.0.0.1:8912"
if not exist "dist\index.html" (
  echo Building the dashboard...
  call npm.cmd run build
  if errorlevel 1 goto failed
)
echo.
echo AgentGuard: http://127.0.0.1:8912
echo Keep this window open. Press Ctrl+C to stop.
echo.
python backend/run.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo AgentGuard could not start. Check the error above.
pause
exit /b 1
