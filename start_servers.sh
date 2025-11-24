#!/bin/bash
# Startup script for Job MCP Agent servers (Linux/Mac)
# This script helps you quickly start the different server components

echo "========================================"
echo "Job MCP Agent - Server Startup"
echo "========================================"
echo ""

show_menu() {
    echo "Please select which server to start:"
    echo ""
    echo "1. FastAPI REST API Server (port 8000)"
    echo "2. MCP Pipeline Server (port 8002)"
    echo "3. Both Servers (in background)"
    echo "4. Run Job Recommendation Script"
    echo "5. Stop All Servers"
    echo "6. Exit"
    echo ""
}

start_fastapi() {
    echo ""
    echo "Starting FastAPI Server..."
    echo "Server will be available at: http://localhost:8000"
    echo "API docs available at: http://localhost:8000/docs"
    echo ""
    echo "Press Ctrl+C to stop the server"
    echo ""
    python server/api_frontend.py
}

start_mcp() {
    echo ""
    echo "Starting MCP Pipeline Server..."
    echo "Server will be available at: http://localhost:8002/mcp"
    echo ""
    echo "Press Ctrl+C to stop the server"
    echo ""
    python server/mcp_pipeline_server.py
}

start_both() {
    echo ""
    echo "Starting both servers in background..."
    echo "FastAPI will be at: http://localhost:8000"
    echo "MCP will be at: http://localhost:8002/mcp"
    echo ""
    
    # Start FastAPI in background
    python server/api_frontend.py > logs/fastapi.log 2>&1 &
    FASTAPI_PID=$!
    echo "FastAPI started with PID: $FASTAPI_PID"
    
    # Wait a moment
    sleep 2
    
    # Start MCP server in background
    python server/mcp_pipeline_server.py > logs/mcp.log 2>&1 &
    MCP_PID=$!
    echo "MCP Server started with PID: $MCP_PID"
    
    # Save PIDs to file for later stopping
    mkdir -p logs
    echo "$FASTAPI_PID" > logs/fastapi.pid
    echo "$MCP_PID" > logs/mcp.pid
    
    echo ""
    echo "Both servers started!"
    echo "Logs are in: logs/fastapi.log and logs/mcp.log"
    echo "Use option 5 to stop all servers"
    echo ""
}

run_recommend() {
    echo ""
    echo "Job Recommendation Script"
    echo "========================================"
    echo ""
    
    read -p "Enter path to resume file: " resume_path
    read -p "How many jobs to fetch? (default 50): " job_count
    job_count=${job_count:-50}
    read -p "How many recommendations? (default 10): " top_k
    top_k=${top_k:-10}
    
    echo ""
    echo "Running recommendation script..."
    echo ""
    python scripts/recommend_jobs.py --resume "$resume_path" --fetch $job_count --top-k $top_k --verbose
    echo ""
    read -p "Press Enter to continue..."
}

stop_all() {
    echo ""
    echo "Stopping all servers..."
    
    if [ -f logs/fastapi.pid ]; then
        FASTAPI_PID=$(cat logs/fastapi.pid)
        if kill -0 $FASTAPI_PID 2>/dev/null; then
            kill $FASTAPI_PID
            echo "Stopped FastAPI server (PID: $FASTAPI_PID)"
        fi
        rm logs/fastapi.pid
    fi
    
    if [ -f logs/mcp.pid ]; then
        MCP_PID=$(cat logs/mcp.pid)
        if kill -0 $MCP_PID 2>/dev/null; then
            kill $MCP_PID
            echo "Stopped MCP server (PID: $MCP_PID)"
        fi
        rm logs/mcp.pid
    fi
    
    echo "All servers stopped"
    echo ""
}

# Main loop
while true; do
    show_menu
    read -p "Enter your choice (1-6): " choice
    
    case $choice in
        1)
            start_fastapi
            ;;
        2)
            start_mcp
            ;;
        3)
            start_both
            ;;
        4)
            run_recommend
            ;;
        5)
            stop_all
            ;;
        6)
            echo ""
            echo "Goodbye!"
            exit 0
            ;;
        *)
            echo "Invalid choice, please try again"
            echo ""
            ;;
    esac
done
