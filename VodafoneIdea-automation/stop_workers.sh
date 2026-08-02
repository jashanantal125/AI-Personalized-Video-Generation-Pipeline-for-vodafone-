#!/bin/bash
# stop_workers.sh - Stop all video workers gracefully

LOG_DIR="/home/ecore/vicode/VodafoneIdea/logs"

echo "Stopping all video workers..."

# Send SIGTERM to all script_2.py processes
pkill -TERM -f "script_2.py"

echo "Waiting for workers to shut down gracefully (10 seconds)..."
sleep 10

# Force kill if still running
remaining=$(ps aux | grep -c "[s]cript_2.py")
if [ $remaining -gt 0 ]; then
    echo "Force killing $remaining remaining workers..."
    pkill -9 -f "script_2.py"
    sleep 2
fi

# Clean up PID files
rm -f $LOG_DIR/worker-*.pid

echo "All workers stopped!"
ps aux | grep script_2
