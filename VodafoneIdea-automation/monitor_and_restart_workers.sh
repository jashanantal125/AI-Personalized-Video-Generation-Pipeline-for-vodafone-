#!/bin/bash
# monitor_and_restart_workers.sh - Monitor workers and auto-restart if needed
# This script should be run via cron every 5 minutes

TOTAL_INSTANCES=12
SCRIPT_PATH="/home/ecore/vicode/VodafoneIdea/script_2.py"
LOG_DIR="/home/ecore/vicode/VodafoneIdea/logs"
PYTHON_BIN="/home/ecore/vicode/VodafoneIdea/venv/bin/python3"
WORK_DIR="/home/ecore/VodafoneIdea"
MONITOR_LOG="$LOG_DIR/monitor.log"
RESTART_SCRIPT="/home/ecore/vicode/VodafoneIdea/start_workers.sh"

# Email configuration (to be implemented in send_email function)
ALERT_EMAIL="your-email@example.com"

# Create log directory if it doesn't exist
mkdir -p $LOG_DIR

# Function to log messages
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> $MONITOR_LOG
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to send email alert (placeholder - implement actual email logic)
send_email_alert() {
    subject="$1"
    body="$2"
    
    # TODO: Implement actual email sending
    # Example using mail command (requires mailutils):
    # echo "$body" | mail -s "$subject" $ALERT_EMAIL
    
    # Example using Python with the email_alert function:
    # python3 -c "from script_2 import email_alert; email_alert('$subject', '$body')"
    
    # For now, just log it
    log_message "EMAIL ALERT: $subject - $body"
}

# Function to start a single worker
start_worker() {
    instance_id=$1
    cd $WORK_DIR
    nohup $PYTHON_BIN script_2.py $instance_id $TOTAL_INSTANCES > $LOG_DIR/worker-$instance_id.log 2>&1 &
    echo $! > $LOG_DIR/worker-$instance_id.pid
    log_message "Started worker instance $instance_id (PID: $!)"
}

# Function to check if worker is running
is_worker_running() {
    instance_id=$1
    pid_file="$LOG_DIR/worker-$instance_id.pid"
    
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if ps -p $pid > /dev/null 2>&1; then
            return 0  # Running
        fi
    fi
    return 1  # Not running
}

# Main monitoring logic
log_message "=== Starting worker monitor check ==="

stopped_workers=()
restarted_workers=()
failed_restarts=()

# Check each worker
for i in $(seq 0 $((TOTAL_INSTANCES-1))); do
    if ! is_worker_running $i; then
        log_message "Worker $i is NOT running!"
        stopped_workers+=($i)
        
        # Attempt to restart
        log_message "Attempting to restart worker $i..."
        start_worker $i
        sleep 3
        
        # Verify restart
        if is_worker_running $i; then
            log_message "Successfully restarted worker $i"
            restarted_workers+=($i)
        else
            log_message "FAILED to restart worker $i"
            failed_restarts+=($i)
        fi
    fi
done

# Count running workers
running_count=$(ps aux | grep -c "[s]cript_2.py")

# Report status
if [ ${#stopped_workers[@]} -eq 0 ]; then
    log_message "All $TOTAL_INSTANCES workers are running. Status: OK"
else
    log_message "Found ${#stopped_workers[@]} stopped workers: ${stopped_workers[*]}"
    
    if [ ${#restarted_workers[@]} -gt 0 ]; then
        log_message "Successfully restarted ${#restarted_workers[@]} workers: ${restarted_workers[*]}"
        send_email_alert "Workers Auto-Restarted" "Workers ${restarted_workers[*]} were stopped and have been automatically restarted. Current status: $running_count/$TOTAL_INSTANCES workers running."
    fi
    
    if [ ${#failed_restarts[@]} -gt 0 ]; then
        log_message "CRITICAL: Failed to restart ${#failed_restarts[@]} workers: ${failed_restarts[*]}"
        send_email_alert "CRITICAL: Worker Restart Failed" "Failed to restart workers: ${failed_restarts[*]}. Manual intervention required. Current status: $running_count/$TOTAL_INSTANCES workers running."
    fi
fi

# Check if too many workers are down (more than 50%)
if [ $running_count -lt $((TOTAL_INSTANCES / 2)) ]; then
    log_message "CRITICAL: Only $running_count out of $TOTAL_INSTANCES workers running!"
    send_email_alert "CRITICAL: Majority of Workers Down" "Only $running_count out of $TOTAL_INSTANCES workers are running. System may have rebooted or experienced critical failure. Attempted auto-restart."
fi

log_message "=== Monitor check completed. Running workers: $running_count/$TOTAL_INSTANCES ==="
echo ""
