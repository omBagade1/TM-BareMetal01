@echo off
setlocal
cd /d "%~dp0"
python backend/configure_cli_listing.py --apply
if errorlevel 1 (
  echo Setup failed. Review the error above.
  pause
  exit /b 1
)
echo Restart AgentGuard using start-agentguard.cmd, then start a new session.
pause
