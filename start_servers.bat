@echo off
REM Startup script for Job MCP Agent servers
REM This script helps you quickly start the different server components

echo ========================================
echo Job MCP Agent - Server Startup
echo ========================================
echo.

:menu
echo Please select which server to start:
echo.
echo 1. FastAPI REST API Server (port 8000)
echo 2. MCP Pipeline Server (port 8002)
echo 3. Both Servers (in separate windows)
echo 4. Run Job Recommendation Script
echo 5. Exit
echo.

set /p choice="Enter your choice (1-5): "

if "%choice%"=="1" goto fastapi
if "%choice%"=="2" goto mcp
if "%choice%"=="3" goto both
if "%choice%"=="4" goto recommend
if "%choice%"=="5" goto end
goto menu

:fastapi
echo.
echo Starting FastAPI Server...
echo Server will be available at: http://localhost:8000
echo API docs available at: http://localhost:8000/docs
echo.
echo Press Ctrl+C to stop the server
echo.
python server\api_frontend.py
goto end

:mcp
echo.
echo Starting MCP Pipeline Server...
echo Server will be available at: http://localhost:8002/mcp
echo.
echo Press Ctrl+C to stop the server
echo.
python server\mcp_pipeline_server.py
goto end

:both
echo.
echo Starting both servers in separate windows...
echo FastAPI will be at: http://localhost:8000
echo MCP will be at: http://localhost:8002/mcp
echo.
start "FastAPI Server" cmd /k python server\api_frontend.py
timeout /t 2 /nobreak >nul
start "MCP Server" cmd /k python server\mcp_pipeline_server.py
echo.
echo Both servers started in separate windows!
echo Close the command windows to stop the servers.
echo.
pause
goto end

:recommend
echo.
echo Job Recommendation Script
echo ========================================
echo.
set /p resume_path="Enter path to resume file: "
set /p job_count="How many jobs to fetch? (default 50): "
if "%job_count%"=="" set job_count=50
set /p top_k="How many recommendations? (default 10): "
if "%top_k%"=="" set top_k=10

echo.
echo Running recommendation script...
echo.
python scripts\recommend_jobs.py --resume "%resume_path%" --fetch %job_count% --top-k %top_k% --verbose
echo.
pause
goto end

:end
echo.
echo Goodbye!
