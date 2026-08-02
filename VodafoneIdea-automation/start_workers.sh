#!/bin/bash
# start_workers.sh - Updated for vicode location with virtual environment
# Configuration
TOTAL_INSTANCES=20
SCRIPT_PATH="/home/ecore/vicode/VodafoneIdea/script_2.py"
LOG_DIR="/home/ecore/vicode/VodafoneIdea/logs"
PYTHON_BIN="/home/ecore/vicode/VodafoneIdea/venv/bin/python3"  # Virtual environment Python
WORK_DIR="/home/ecore/vicode/VodafoneIdea"

# Create log directory
mkdir -p $LOG_DIR

# Function to start a worker instance
start_worker() {
    instance_id=$1
    cd $WORK_DIR
    nohup $PYTHON_BIN script_2.py $instance_id $TOTAL_INSTANCES > $LOG_DIR/worker-$instance_id.log 2>&1 &
    echo $! > $LOG_DIR/worker-$instance_id.pid
    echo "Started video worker instance $instance_id (PID: $!)"
}

# Stop existing workers
echo "Stopping existing video workers..."
pkill -f "script_2.py"
sleep 2

# Clean up stale PID files
rm -f $LOG_DIR/worker-*.pid

# Start new workers
echo "Starting $TOTAL_INSTANCES video worker instances..."
for i in $(seq 0 $((TOTAL_INSTANCES-1))); do
    start_worker $i
    sleep 2
done

echo "All video workers started!"
echo ""
echo "Monitor logs: tail -f $LOG_DIR/worker-*.log"
echo "Check processes: ps aux | grep script_2"
echo "Check status: ./status_workers.sh"
