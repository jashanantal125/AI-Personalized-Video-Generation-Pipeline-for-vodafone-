#!/bin/bash

# DB Config
DB_USER="root"
DB_PASS="YOUR_DB_PASSWORD"
DB_NAME="vi"

echo "=== Video Worker Process Status ==="
ps aux | grep script_2.py | grep -v grep

echo ""
echo "=== Processing Queue Status ==="
mysql -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" -e "
SELECT 
    status, 
    COUNT(*) as count,
    COUNT(DISTINCT circle_name) as unique_circles
FROM users 
WHERE status IN ('pending', 'processing', 'processed', 'failed') 
GROUP BY status;
" 2>/dev/null

echo ""
echo "=== Circle-wise Processing Status ==="
mysql -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" -e "
SELECT 
    COALESCE(circle_name, 'NULL') as circle,
    status,
    COUNT(*) as count
FROM users 
WHERE status IN ('pending', 'processing', 'processed', 'failed')
GROUP BY circle_name, status
ORDER BY circle_name, status;
" 2>/dev/null

echo ""
echo "=== Processing Rate (last hour) ==="
mysql -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" -e "
SELECT 
    COUNT(*) as completed_last_hour,
    COUNT(DISTINCT circle_name) as circles_processed
FROM users 
WHERE status = 'processed' 
AND processing_started_at > NOW() - INTERVAL 1 HOUR;
" 2>/dev/null

echo ""
echo "=== Active Workers ==="
mysql -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" -e "
SELECT 
    worker_id,
    COUNT(*) as currently_processing,
    MIN(processing_started_at) as oldest_job
FROM users 
WHERE status = 'processing' 
GROUP BY worker_id
ORDER BY worker_id;
" 2>/dev/null

echo ""
echo "=== Recent Processed Videos ==="
mysql -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" -e "
SELECT 
    COUNT(*) as total_processed_today,
    COUNT(DISTINCT circle_name) as circles_today
FROM users 
WHERE status = 'processed' 
AND DATE(created_at) = CURDATE();
" 2>/dev/null

echo ""
echo "=== Log Files Status ==="
LOG_DIR="/home/ecore/vicode/logs"
if [ -d "$LOG_DIR" ]; then
    echo "Recent log files:"
    ls -la $LOG_DIR/worker-*.log 2>/dev/null | tail -5
    echo ""
    echo "Worker PID files:"
    ls -la $LOG_DIR/worker-*.pid 2>/dev/null | wc -l
    echo "workers currently running"
else
    echo "Log directory not found: $LOG_DIR"
fi
