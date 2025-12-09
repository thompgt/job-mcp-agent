#!/usr/bin/env python3
"""
Cross-platform launcher for Job MCP Agent
Starts both MCP server and web frontend, then opens browser
"""
import os
import sys
import time
import subprocess
import webbrowser
from pathlib import Path

def main():
    """Launch the Job MCP Agent application."""
    print("=" * 50)
    print("  Job MCP Agent Launcher")
    print("=" * 50)
    print()
    
    # Get the project root directory
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
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
        mcp_server = subprocess.Popen(
            [sys.executable, "server/mcp_pipeline_server.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )
        processes.append(("MCP Server", mcp_server))
        time.sleep(3)
        
        # Start web frontend
        print("Starting Web Frontend on port 8000...")
        web_frontend = subprocess.Popen(
            [sys.executable, "web_frontend.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
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
        print("Press Ctrl+C to stop all servers...")
        
        # Wait for user interrupt
        try:
            while True:
                time.sleep(1)
                # Check if any process died
                for name, proc in processes:
                    if proc.poll() is not None:
                        print(f"\nWarning: {name} stopped unexpectedly")
        except KeyboardInterrupt:
            print("\n\nStopping servers...")
    
    finally:
        # Clean up all processes
        for name, proc in processes:
            try:
                proc.terminate()
                proc.wait(timeout=5)
                print(f"{name} stopped")
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"{name} force killed")
            except Exception as e:
                print(f"Error stopping {name}: {e}")
        
        print("\nAll servers stopped.")
        print("Press Enter to exit...")
        input()

if __name__ == "__main__":
    main()
