# 🚀 Job MCP Agent Launcher

Multiple ways to launch the Job MCP Agent application with a single click!

## 📋 Launcher Options

### 1. **launch.bat** (Recommended for Windows)
Double-click to start both servers in separate terminal windows.
- Shows server logs in separate windows
- Opens browser automatically
- Press any key in the main window to stop all servers
- Easy to see what's happening

**Usage:**
```
Double-click launch.bat
```

### 2. **launch.vbs** (Silent Mode)
Double-click to start servers completely hidden (no terminal windows).
- Cleanest user experience
- Runs silently in background
- Opens browser automatically
- Shows notification when ready
- Use `stop_servers.bat` to stop

**Usage:**
```
Double-click launch.vbs
```

### 3. **launch_silent.bat** (Background Mode)
Starts servers in background without keeping terminal open.
- No terminal windows stay open
- Minimal UI
- Use `stop_servers.bat` to stop

**Usage:**
```
Double-click launch_silent.bat
```

### 4. **launch.py** (Cross-Platform)
Python-based launcher that works on Windows, Mac, and Linux.
- Cross-platform compatible
- Shows server status
- Press Ctrl+C to stop all servers
- Good for debugging

**Usage:**
```bash
python launch.py
```

### 5. **stop_servers.bat** (Stop All)
Stops all running Job MCP Agent servers.

**Usage:**
```
Double-click stop_servers.bat
```

## 🎯 Quick Start

**Easiest way (Windows):**
1. Double-click `launch.vbs` for silent startup
2. Wait for browser to open automatically
3. Start using the application!
4. When done, double-click `stop_servers.bat`

**With logs visible:**
1. Double-click `launch.bat`
2. See server logs in separate windows
3. Press any key in main window to stop

## 🔧 What Gets Started

Both launchers start:
1. **MCP Pipeline Server** on `http://127.0.0.1:8002/mcp`
2. **Web Frontend** on `http://127.0.0.1:8000`
3. **Browser** automatically opens to frontend

## 📝 Notes

- Make sure MongoDB is running if using database features
- Make sure Ollama is running for cover letter generation
- Servers take 3-5 seconds to fully start
- If port 8000 or 8002 is already in use, edit the Python files to change ports

## 🛠️ Troubleshooting

**Servers won't start:**
- Check if Python is in your PATH
- Check if ports 8000 and 8002 are available
- Run `python --version` to verify Python installation

**Can't stop servers:**
- Use Task Manager to kill `python.exe` or `pythonw.exe` processes
- Or run `taskkill /F /IM python.exe` in cmd

**Browser doesn't open:**
- Manually navigate to http://127.0.0.1:8000
- Check if web frontend started successfully

## 🎨 Creating Desktop Shortcuts

**For launch.vbs (recommended):**
1. Right-click `launch.vbs`
2. Select "Create shortcut"
3. Move shortcut to Desktop
4. Rename to "Job MCP Agent"
5. Right-click shortcut → Properties → Change Icon (optional)

**For launch.bat:**
1. Right-click `launch.bat`
2. Select "Create shortcut"
3. Move shortcut to Desktop
4. Right-click shortcut → Properties
5. Change "Run" to "Minimized" (optional)
