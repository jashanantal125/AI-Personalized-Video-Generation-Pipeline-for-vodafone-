#!/bin/bash

# stop_workers.sh - Updated for vicode location

LOG_DIR="/home/ecore/vicode/logs"

echo "Stopping all video processor workers..."
pkill -f "script_2.py"

# Remove PID files
rm -f $LOG_DIR/worker-*.pid

echo "All workers stopped!"
echo "Cleaning up any remaining temp directories..."

# Clean up temp directories created by workers
cd /home/ecore/vicode/
rm -rf temp_worker_*

echo "Cleanup complete!"
