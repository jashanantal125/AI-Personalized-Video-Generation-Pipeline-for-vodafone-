#!/bin/bash
# realtime_video_sync_v4.sh - With periodic sweep for missed files

SOURCE_DIR="/home/ecore/vicode/VodafoneIdea/output_videos_vi/"
DEST_USER="ecore"
DEST_HOST="10.0.0.1"
DEST_DIR="/var/www/html/vid/"
LOG_FILE="/home/ecore/rsync_video.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== Real-time sync service started (with sweep) =====" >> "$LOG_FILE"

# Function to sync a single file
sync_file() {
    local FILEPATH="$1"
    local FILENAME=$(basename "$FILEPATH")
    
    # Skip if file doesn't exist (might have been deleted)
    if [ ! -f "$FILEPATH" ]; then
        return
    fi
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Syncing file: $FILENAME" >> "$LOG_FILE"
    
    rsync -avz --remove-source-files --chmod=664 "$FILEPATH" "${DEST_USER}@${DEST_HOST}:${DEST_DIR}" 2>&1 | \
    awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' >> "$LOG_FILE"
    
    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Successfully synced: $FILENAME" >> "$LOG_FILE"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR syncing: $FILENAME" >> "$LOG_FILE"
    fi
}

# Periodic sweep function (runs in background)
periodic_sweep() {
    while true; do
        sleep 60  # Check every 60 seconds
        
        # Find all .mp4 files and sync them
        find "$SOURCE_DIR" -maxdepth 1 -name "*.mp4" -type f | while read FILEPATH; do
            sync_file "$FILEPATH"
        done
    done
}

# Start periodic sweep in background
periodic_sweep &
SWEEP_PID=$!

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Periodic sweep started (PID: $SWEEP_PID)" >> "$LOG_FILE"

# Monitor directory for new files in real-time
inotifywait -m -e close_write -e moved_to "$SOURCE_DIR" --format '%w%f' | while read FILEPATH
do
    sync_file "$FILEPATH"
done
