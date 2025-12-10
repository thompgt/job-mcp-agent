@echo off
REM Career Craft Agent Launcher
REM Starts both the MCP server and web frontend

echo.
echo ====================================
echo  Career Craft Agent Launcher
echo ====================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found in PATH
    pause
    exit /b 1
)

echo Starting MCP Pipeline Server on port 8002...
start "MCP Server" cmd /k "python server\mcp_pipeline_server.py"

REM Wait a moment for the server to start
timeout /t 3 /nobreak >nul

echo Starting Web Frontend on port 8000...
start "Web Frontend" cmd /k "python web_frontend.py"

REM Wait a moment for the frontend to start
timeout /t 3 /nobreak >nul

echo.
echo ====================================
echo  Both servers are starting...
echo ====================================
echo.
echo MCP Server:    http://127.0.0.1:8002/mcp
echo Web Frontend:  http://127.0.0.1:8000
echo.
echo Opening web browser...
timeout /t 2 /nobreak >nul

REM Open the web frontend in default browser
start http://127.0.0.1:8000

echo.
echo Both servers are running in separate windows.
echo Close those windows to stop the servers.
echo.
pause
