@echo off
REM Silent launcher - runs servers in background without terminal windows

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found in PATH
    pause
    exit /b 1
)

echo Starting Job MCP Agent...

REM Start MCP server in background
start /B pythonw server\mcp_pipeline_server.py

REM Wait for server to initialize
timeout /t 3 /nobreak >nul

REM Start web frontend in background
start /B pythonw web_frontend.py

REM Wait for frontend to initialize
timeout /t 3 /nobreak >nul

REM Open browser
start http://127.0.0.1:8000

echo Job MCP Agent is running!
echo.
echo MCP Server:    http://127.0.0.1:8002/mcp
echo Web Frontend:  http://127.0.0.1:8000
echo.
echo To stop the servers, run: taskkill /F /IM pythonw.exe
echo.
