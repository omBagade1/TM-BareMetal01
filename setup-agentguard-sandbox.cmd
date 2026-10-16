@echo off
setlocal
cd /d "%~dp0"
if not defined AGENTGUARD_WORKSPACE set "AGENTGUARD_WORKSPACE=%~dp0workspace"
if not defined AGENTGUARD_DATA set "AGENTGUARD_DATA=%~dp0data"
echo.
echo AgentGuard Windows sandbox setup
echo Run under the same normal Windows account as start-agentguard.cmd.
echo This creates an AppContainer profile and scoped workspace permissions.
echo No elevation or global firewall changes are requested.
echo.
python backend/setup_windows_sandbox.py --workspace "%AGENTGUARD_WORKSPACE%" --audit-dir "%AGENTGUARD_DATA%" --plan
if errorlevel 1 goto failed
if /I "%~1"=="--plan" exit /b 0
echo.
echo Applying the setup printed above...
python backend/setup_windows_sandbox.py --workspace "%AGENTGUARD_WORKSPACE%" --audit-dir "%AGENTGUARD_DATA%" --apply
if errorlevel 1 goto failed
echo.
echo Checking actual isolated worker startup...
python backend/check_sandbox.py
if errorlevel 1 goto failed
echo.
echo Worker startup succeeded. Restart AgentGuard and start a new Ollama session.
echo This startup check does not certify network or filesystem attack containment.
pause
exit /b 0
:failed
echo.
echo SETUP OR WORKER CHECK FAILED. Copy the error above for troubleshooting.
echo File tools remain unavailable; do not disable the sandbox to bypass this.
pause
exit /b 1
