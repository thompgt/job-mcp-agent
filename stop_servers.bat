@echo off
REM Stop all running Career Craft Agent servers

echo Stopping Career Craft Agent servers...

REM Kill Python processes running the servers
taskkill /F /IM python.exe /FI "WINDOWTITLE eq MCP Server*" >nul 2>&1
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Web Frontend*" >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1

echo.
echo All servers stopped.
timeout /t 2 /nobreak >nul
