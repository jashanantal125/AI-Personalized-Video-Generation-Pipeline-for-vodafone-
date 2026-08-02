#!/bin/bash
# status_workers.sh - Check status of video workers

TOTAL_INSTANCES=20
LOG_DIR="/home/ecore/vicode/VodafoneIdea/logs"
SCRIPT_NAME="script_2.py"

echo "=========================================="
echo "Video Worker Status Check"
echo "=========================================="
echo ""

# Count running workers
running_count=$(ps aux | grep -c "[s]cript_2.py")
echo "Running workers: $running_count / $TOTAL_INSTANCES"
echo ""

# Check each worker instance
echo "Individual Worker Status:"
echo "----------------------------------------"
for i in $(seq 0 $((TOTAL_INSTANCES-1))); do
    pid_file="$LOG_DIR/worker-$i.pid"
    
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if ps -p $pid > /dev/null 2>&1; then
            echo "Worker $i: RUNNING (PID: $pid)"
        else
            echo "Worker $i: STOPPED (stale PID file)"
        fi
    else
        echo "Worker $i: STOPPED (no PID file)"
    fi
done

echo ""
echo "=========================================="
echo "Recent Activity (last 10 lines per worker):"
echo "=========================================="
for i in $(seq 0 $((TOTAL_INSTANCES-1))); do
    log_file="$LOG_DIR/video_worker_${i}_$(date +%Y%m%d).log"
    if [ -f "$log_file" ]; then
        echo ""
        echo "--- Worker $i (last 10 lines) ---"
        tail -n 10 "$log_file"
    fi
done
