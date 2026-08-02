#!/bin/bash
# realtime_video_sync_v5.sh - Ultra-fast sync with 5-second sweep

SOURCE_DIR="/home/ecore/vicode/VodafoneIdea/output_videos_vi/"
DEST_USER="ecore"
DEST_HOST="10.0.0.1"
DEST_DIR="/var/www/html/vid/"
LOG_FILE="/home/ecore/rsync_video.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== Real-time sync service started (5-second sweep) =====" >> "$LOG_FILE"

# Function to sync all pending files at once
sync_all_files() {
    # Find all .mp4 files and sync them in one go
    local files=$(find "$SOURCE_DIR" -maxdepth 1 -name "*.mp4" -type f)
    
    if [ -n "$files" ]; then
        local count=$(echo "$files" | wc -l)
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Found $count file(s) to sync" >> "$LOG_FILE"
        
        # Sync all files at once using rsync with wildcard
        rsync -avz --remove-source-files "$SOURCE_DIR"*.mp4 "${DEST_USER}@${DEST_HOST}:${DEST_DIR}" 2>&1 | \
        awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' >> "$LOG_FILE"
        
        if [ ${PIPESTATUS[0]} -eq 0 ]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Successfully synced $count file(s)" >> "$LOG_FILE"
        else
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR during bulk sync" >> "$LOG_FILE"
        fi
    fi
}

# Periodic sweep function - checks every 5 seconds
periodic_sweep() {
    while true; do
        sleep 5  # Check every 5 seconds
        sync_all_files
    done
}

# Start periodic sweep in background
periodic_sweep &
SWEEP_PID=$!

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 5-second periodic sweep started (PID: $SWEEP_PID)" >> "$LOG_FILE"

# Monitor directory for new files in real-time (immediate sync)
inotifywait -m -e close_write -e moved_to "$SOURCE_DIR" --format '%w%f' | while read FILEPATH
do
    FILENAME=$(basename "$FILEPATH")
    
    # Skip if file doesn't exist
    if [ ! -f "$FILEPATH" ]; then
        continue
    fi
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] New file detected: $FILENAME" >> "$LOG_FILE"
    
    # Immediate sync
    rsync -avz --remove-source-files "$FILEPATH" "${DEST_USER}@${DEST_HOST}:${DEST_DIR}" 2>&1 | \
    awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' >> "$LOG_FILE"
    
    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Successfully synced: $FILENAME" >> "$LOG_FILE"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR syncing: $FILENAME" >> "$LOG_FILE"
    fi
done
