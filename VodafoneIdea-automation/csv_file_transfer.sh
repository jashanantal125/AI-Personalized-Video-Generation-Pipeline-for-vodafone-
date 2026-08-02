#!/bin/bash

# Variables
SOURCE_DIR="/home/ecore/vicode/VodafoneIdea/output_videos_vi/"              # Path on server1
DEST_USER="ecore"                                              # Username on server2
DEST_HOST="10.0.0.1"                                       # Hostname or IP of server2
DEST_DIR="/var/www/html/vid/"     # Destination path on server2
LOG_FILE="/home/ecore/rsync_video.log"                          # Log file

# Start log entry
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== Starting sync job =====" >> "$LOG_FILE"

# Check if any files exist to transfer
if find "$SOURCE_DIR" -type f | grep -q .; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Files found. Running rsync..." >> "$LOG_FILE"

    # Rsync with timestamped output
    rsync -avz "$SOURCE_DIR" "${DEST_USER}@${DEST_HOST}:${DEST_DIR}" 2>&1 | \
    awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' >> "$LOG_FILE"

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync completed successfully." >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No files to sync." >> "$LOG_FILE"
fi

# End log entry
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== Sync job finished =====" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

