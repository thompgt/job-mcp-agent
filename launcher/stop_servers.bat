@echo off
REM Stop all running Job MCP Agent servers

echo Stopping Job MCP Agent servers...

REM Kill Python processes running the servers
taskkill /F /IM python.exe /FI "WINDOWTITLE eq MCP Server*" >nul 2>&1
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Web Frontend*" >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1

echo.
echo All servers stopped.
timeout /t 2 /nobreak >nul
