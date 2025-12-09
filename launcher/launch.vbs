' VBScript launcher - double-click to start without any terminal windows
Set WshShell = CreateObject("WScript.Shell")

' Change to the script directory
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

' Start MCP server (hidden)
WshShell.Run "pythonw server\mcp_pipeline_server.py", 0, False

' Wait 3 seconds for server to start
WScript.Sleep 3000

' Start web frontend (hidden)
WshShell.Run "pythonw web_frontend.py", 0, False

' Wait 3 seconds for frontend to start
WScript.Sleep 3000

' Open browser
WshShell.Run "http://127.0.0.1:8000", 1, False

' Show notification
MsgBox "Job MCP Agent is running!" & vbCrLf & vbCrLf & _
       "MCP Server: http://127.0.0.1:8002/mcp" & vbCrLf & _
       "Web Frontend: http://127.0.0.1:8000" & vbCrLf & vbCrLf & _
       "To stop, run stop_servers.bat", _
       vbInformation, "Job MCP Agent"
