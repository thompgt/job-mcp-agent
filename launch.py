#!/usr/bin/env python3
"""
Cross-platform launcher for Career Craft Agent
Starts both MCP server and web frontend, then opens browser
"""
import os
import sys
import time
import subprocess
import webbrowser
from pathlib import Path

def main():
    """Launch the Career Craft Agent application."""
    print("=" * 50)
    print("  Career Craft Agent Launcher")
    print("=" * 50)
    print()
    
    # Ensure we're in the project root
    project_root = Path(__file__).parent
    os.chdir(project_root)
    print(f"Working directory: {project_root}")
    print()
    
    # Check if Python is available
    try:
        subprocess.run([sys.executable, "--version"], 
                      check=True, 
                      capture_output=True)
    except subprocess.CalledProcessError:
        print("Error: Python not found")
        input("Press Enter to exit...")
        sys.exit(1)
    
    processes = []
    
    try:
        # Start MCP server
        print("Starting MCP Pipeline Server on port 8002...")
        if sys.platform == "win32":
            # On Windows, create a batch file command and execute it
            cmd = f'start "MCP Server" cmd /k "{sys.executable}" server\\mcp_pipeline_server.py'
            mcp_server = subprocess.Popen(cmd, shell=True)
        else:
            # On Unix-like systems
            mcp_server = subprocess.Popen(
                [sys.executable, "server/mcp_pipeline_server.py"]
            )
        processes.append(("MCP Server", mcp_server))
        time.sleep(3)
        
        # Start web frontend
        print("Starting Web Frontend on port 8000...")
        if sys.platform == "win32":
            # On Windows, create a batch file command and execute it
            cmd = f'start "Web Frontend" cmd /k "{sys.executable}" web_frontend.py'
            web_frontend = subprocess.Popen(cmd, shell=True)
        else:
            # On Unix-like systems
            web_frontend = subprocess.Popen(
                [sys.executable, "web_frontend.py"]
            )
        processes.append(("Web Frontend", web_frontend))
        time.sleep(3)
        
        print()
        print("=" * 50)
        print("  Both servers are running!")
        print("=" * 50)
        print()
        print("MCP Server:    http://127.0.0.1:8002/mcp")
        print("Web Frontend:  http://127.0.0.1:8000")
        print()
        print("Opening web browser...")
        
        # Open browser
        time.sleep(2)
        webbrowser.open("http://127.0.0.1:8000")
        
        print()
        print("Both servers are running in separate windows.")
        print("Close those windows to stop the servers.")
        print()
        input("Press Enter to exit launcher...")
    
    except Exception as e:
        print(f"\nError: {e}")
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()
