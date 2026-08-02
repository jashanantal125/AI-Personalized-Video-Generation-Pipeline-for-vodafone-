#!/bin/bash

# Configuration
REMOTE_HOST="172.27.32.20"
REMOTE_USER="admin"
REMOTE_PASSWORD="YOUR_SFTP_PASSWORD"
REMOTE_DIR="/ENC_UPC_Data/BOAT/"
LOCAL_DIR="$HOME/vicode/VodafoneIdea/sp_files"

# Create local directory if it doesn't exist
mkdir -p "$LOCAL_DIR"

# Log file
LOG_FILE="$HOME/boat_download_today.log"

# Get current timestamp
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TIMESTAMP] Starting download for today 00:00 to 10:00..." >> "$LOG_FILE"

# Get today's date in required format
TODAY=$(date '+%Y_%m_%d')
echo "Looking for files from: BOAT_${TODAY}_00_00_00.csv to BOAT_${TODAY}_10_00_00.csv" >> "$LOG_FILE"

# Create batch file to list files on server
LIST_BATCH=$(mktemp)
cat > "$LIST_BATCH" << EOFBATCH
cd $REMOTE_DIR
ls -1
bye
EOFBATCH

# Get list of all files from server
ALL_REMOTE_FILES=$(sshpass -p "$REMOTE_PASSWORD" sftp -oBatchMode=no -o HostKeyAlgorithms=+ssh-rsa,ssh-dss -o PubkeyAcceptedKeyTypes=+ssh-rsa -b "$LIST_BATCH" "$REMOTE_USER@$REMOTE_HOST" 2>/dev/null | grep "^BOAT_.*\.csv$")
rm -f "$LIST_BATCH"

if [ -z "$ALL_REMOTE_FILES" ]; then
    echo "[$TIMESTAMP] No files found on server" >> "$LOG_FILE"
    exit 0
fi

# Filter files for today between 00:00:00 and 10:00:00
FILES_TO_DOWNLOAD=""
while IFS= read -r filename; do
    if [ ! -z "$filename" ]; then
        # Extract date and time from filename: BOAT_YYYY_MM_DD_HH_MM_SS.csv
        if [[ $filename =~ BOAT_([0-9]{4})_([0-9]{2})_([0-9]{2})_([0-9]{2})_([0-9]{2})_([0-9]{2})\.csv ]]; then
            file_date="${BASH_REMATCH[1]}_${BASH_REMATCH[2]}_${BASH_REMATCH[3]}"
            file_hour="${BASH_REMATCH[4]}"
            
            # Check if file is from today and hour is between 00 and 10 (inclusive of 00, exclusive of 10)
            if [ "$file_date" = "$TODAY" ] && [ "$file_hour" -ge 0 ] && [ "$file_hour" -lt 10 ]; then
                FILES_TO_DOWNLOAD="$FILES_TO_DOWNLOAD
$filename"
            fi
        fi
    fi
done <<< "$ALL_REMOTE_FILES"

FILES_TO_DOWNLOAD=$(echo "$FILES_TO_DOWNLOAD" | grep -v '^$' | sort -u)

if [ -z "$FILES_TO_DOWNLOAD" ]; then
    echo "[$TIMESTAMP] No matching files found for today 00:00-10:00" >> "$LOG_FILE"
    exit 0
fi

echo "[$TIMESTAMP] Found $(echo "$FILES_TO_DOWNLOAD" | wc -l) files to process" >> "$LOG_FILE"

# Download files
DOWNLOADED_COUNT=0
SKIPPED_COUNT=0

echo "$FILES_TO_DOWNLOAD" | while read -r filename; do
    if [ ! -z "$filename" ]; then
        # Check if file already exists locally
        if [ -f "$LOCAL_DIR/$filename" ]; then
            echo "[$TIMESTAMP] File already exists: $filename - SKIPPED" >> "$LOG_FILE"
            SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
        else
            echo "[$TIMESTAMP] Downloading new file: $filename" >> "$LOG_FILE"
            
            # Download this specific file
            DOWNLOAD_BATCH=$(mktemp)
            cat > "$DOWNLOAD_BATCH" << EOFDOWNLOAD
cd $REMOTE_DIR
lcd $LOCAL_DIR
get $filename
bye
EOFDOWNLOAD
            
            sshpass -p "$REMOTE_PASSWORD" sftp -oBatchMode=no -o HostKeyAlgorithms=+ssh-rsa,ssh-dss -o PubkeyAcceptedKeyTypes=+ssh-rsa -b "$DOWNLOAD_BATCH" "$REMOTE_USER@$REMOTE_HOST" >> "$LOG_FILE" 2>&1
            
            if [ $? -eq 0 ]; then
                DOWNLOADED_COUNT=$((DOWNLOADED_COUNT + 1))
                echo "[$TIMESTAMP] Successfully downloaded: $filename" >> "$LOG_FILE"
            else
                echo "[$TIMESTAMP] Failed to download: $filename" >> "$LOG_FILE"
            fi
            
            rm -f "$DOWNLOAD_BATCH"
        fi
    fi
done

echo "[$TIMESTAMP] Download completed - Downloaded: $DOWNLOADED_COUNT, Skipped: $SKIPPED_COUNT" >> "$LOG_FILE"
