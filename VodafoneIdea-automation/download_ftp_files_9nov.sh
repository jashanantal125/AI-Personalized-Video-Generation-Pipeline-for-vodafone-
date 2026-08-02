#!/bin/bash

# Configuration
REMOTE_HOST="172.27.32.20"
REMOTE_USER="admin"
REMOTE_PASSWORD="YOUR_SFTP_PASSWORD"
REMOTE_DIR="/ENC_UPC_Data/BOAT/"

# Target date configuration (MODIFY THIS)
TARGET_DATE="2025_11_12"  # Format: YYYY_MM_DD
LOCAL_DIR="$HOME/test_current_csv_nos/vi_files_12_nov"

# Create local directory if it doesn't exist
mkdir -p "$LOCAL_DIR"

# Log file
LOG_FILE="$HOME/boat_download_${TARGET_DATE}.log"

# Get current timestamp
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TIMESTAMP] ============================================" >> "$LOG_FILE"
echo "[$TIMESTAMP] Starting download for date: $TARGET_DATE" >> "$LOG_FILE"
echo "[$TIMESTAMP] Target files: BOAT_${TARGET_DATE}_00_00_00.csv to BOAT_${TARGET_DATE}_23_59_59.csv" >> "$LOG_FILE"
echo "[$TIMESTAMP] Local directory: $LOCAL_DIR" >> "$LOG_FILE"

# Create batch file to list files on server
LIST_BATCH=$(mktemp)
cat > "$LIST_BATCH" << EOFBATCH
cd $REMOTE_DIR
ls -1
bye
EOFBATCH

echo "[$TIMESTAMP] Fetching file list from server..." >> "$LOG_FILE"

# Get list of all files from server
ALL_REMOTE_FILES=$(sshpass -p "$REMOTE_PASSWORD" sftp -oBatchMode=no -o HostKeyAlgorithms=+ssh-rsa,ssh-dss -o PubkeyAcceptedKeyTypes=+ssh-rsa -b "$LIST_BATCH" "$REMOTE_USER@$REMOTE_HOST" 2>/dev/null | grep "^BOAT_.*\.csv$")

rm -f "$LIST_BATCH"

if [ -z "$ALL_REMOTE_FILES" ]; then
    echo "[$TIMESTAMP] ERROR: No files found on server" >> "$LOG_FILE"
    exit 1
fi

# Filter files for the target date (all hours 00-23)
FILES_TO_DOWNLOAD=""
while IFS= read -r filename; do
    if [ ! -z "$filename" ]; then
        # Extract date from filename: BOAT_YYYY_MM_DD_HH_MM_SS.csv
        if [[ $filename =~ BOAT_([0-9]{4})_([0-9]{2})_([0-9]{2})_([0-9]{2})_([0-9]{2})_([0-9]{2})\.csv ]]; then
            file_date="${BASH_REMATCH[1]}_${BASH_REMATCH[2]}_${BASH_REMATCH[3]}"
            
            # Check if file is from target date
            if [ "$file_date" = "$TARGET_DATE" ]; then
                FILES_TO_DOWNLOAD="$FILES_TO_DOWNLOAD
$filename"
            fi
        fi
    fi
done <<< "$ALL_REMOTE_FILES"

# Clean up the list and sort
FILES_TO_DOWNLOAD=$(echo "$FILES_TO_DOWNLOAD" | grep -v '^$' | sort -u)

if [ -z "$FILES_TO_DOWNLOAD" ]; then
    echo "[$TIMESTAMP] ERROR: No matching files found for date $TARGET_DATE" >> "$LOG_FILE"
    exit 1
fi

TOTAL_FILES=$(echo "$FILES_TO_DOWNLOAD" | wc -l)
echo "[$TIMESTAMP] Found $TOTAL_FILES files to process" >> "$LOG_FILE"

# Download files
DOWNLOADED_COUNT=0
SKIPPED_COUNT=0
FAILED_COUNT=0

echo "$FILES_TO_DOWNLOAD" | while read -r filename; do
    if [ ! -z "$filename" ]; then
        # Check if file already exists locally
        if [ -f "$LOCAL_DIR/$filename" ]; then
            echo "[$TIMESTAMP] File already exists: $filename - SKIPPED" >> "$LOG_FILE"
            ((SKIPPED_COUNT++))
        else
            echo "[$TIMESTAMP] Downloading: $filename" >> "$LOG_FILE"
            
            # Download this specific file
            DOWNLOAD_BATCH=$(mktemp)
            cat > "$DOWNLOAD_BATCH" << EOFDOWNLOAD
cd $REMOTE_DIR
lcd $LOCAL_DIR
get $filename
bye
EOFDOWNLOAD
            
            sshpass -p "$REMOTE_PASSWORD" sftp -oBatchMode=no -o HostKeyAlgorithms=+ssh-rsa,ssh-dss -o PubkeyAcceptedKeyTypes=+ssh-rsa -b "$DOWNLOAD_BATCH" "$REMOTE_USER@$REMOTE_HOST" >> "$LOG_FILE" 2>&1
            
            if [ $? -eq 0 ] && [ -f "$LOCAL_DIR/$filename" ]; then
                ((DOWNLOADED_COUNT++))
                echo "[$TIMESTAMP] ✓ Successfully downloaded: $filename" >> "$LOG_FILE"
            else
                ((FAILED_COUNT++))
                echo "[$TIMESTAMP] ✗ Failed to download: $filename" >> "$LOG_FILE"
            fi
            
            rm -f "$DOWNLOAD_BATCH"
        fi
    fi
done

# Final summary
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TIMESTAMP] ============================================" >> "$LOG_FILE"
echo "[$TIMESTAMP] Download Summary:" >> "$LOG_FILE"
echo "[$TIMESTAMP] Total files found: $TOTAL_FILES" >> "$LOG_FILE"
echo "[$TIMESTAMP] Downloaded: $DOWNLOADED_COUNT" >> "$LOG_FILE"
echo "[$TIMESTAMP] Skipped (already exists): $SKIPPED_COUNT" >> "$LOG_FILE"
echo "[$TIMESTAMP] Failed: $FAILED_COUNT" >> "$LOG_FILE"
echo "[$TIMESTAMP] ============================================" >> "$LOG_FILE"

# Verify downloaded files
ACTUAL_COUNT=$(ls -1 "$LOCAL_DIR"/BOAT_${TARGET_DATE}_*.csv 2>/dev/null | wc -l)
echo "[$TIMESTAMP] Files in local directory: $ACTUAL_COUNT" >> "$LOG_FILE"

if [ $ACTUAL_COUNT -eq $TOTAL_FILES ]; then
    echo "[$TIMESTAMP] ✓ SUCCESS: All files downloaded successfully!" >> "$LOG_FILE"
    exit 0
else
    echo "[$TIMESTAMP] ⚠ WARNING: Expected $TOTAL_FILES files, but found $ACTUAL_COUNT in local directory" >> "$LOG_FILE"
    exit 1
fi
