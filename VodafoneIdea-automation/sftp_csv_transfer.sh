#!/bin/bash

# Configuration
REMOTE_HOST="172.27.32.20"
REMOTE_USER="admin"
REMOTE_PASSWORD="YOUR_SFTP_PASSWORD"
REMOTE_DIR="/ENC_UPC_Data/BOAT/"
LOCAL_DIR="$HOME/vicode/VodafoneIdea/vi_server_files"

# Create local directory if it doesn't exist
mkdir -p "$LOCAL_DIR"

# Log file
LOG_FILE="$HOME/boat_download.log"

# Get current timestamp
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TIMESTAMP] Starting download check..." >> "$LOG_FILE"

# Generate filename patterns for last 3 minutes only (changed from 6 to 3)
PATTERNS=""
for i in {6..10}; do
    TIME_CHECK=$(date -d "$i minutes ago" '+BOAT_%Y_%m_%d_%H_%M_*.csv')
    PATTERNS="$PATTERNS $TIME_CHECK"
done

echo "Looking for patterns: $PATTERNS" >> "$LOG_FILE"

# Create batch file to list files on server
LIST_BATCH=$(mktemp)
cat > "$LIST_BATCH" << EOFBATCH
cd $REMOTE_DIR
ls -1
bye
EOFBATCH

# Get list of all files from server that match our patterns
ALL_REMOTE_FILES=$(sshpass -p "$REMOTE_PASSWORD" sftp -oBatchMode=no -o HostKeyAlgorithms=+ssh-rsa,ssh-dss -o PubkeyAcceptedKeyTypes=+ssh-rsa -b "$LIST_BATCH" "$REMOTE_USER@$REMOTE_HOST" 2>/dev/null | grep "^BOAT_.*\.csv$")

rm -f "$LIST_BATCH"

if [ -z "$ALL_REMOTE_FILES" ]; then
    echo "[$TIMESTAMP] No files found on server" >> "$LOG_FILE"
    exit 0
fi

# Filter files that match our time patterns
FILES_TO_CHECK=""
for pattern_check in $PATTERNS; do
    # Convert pattern to regex (replace * with .*)
    pattern_regex=$(echo "$pattern_check" | sed 's/\*/.*/')
    matched=$(echo "$ALL_REMOTE_FILES" | grep -E "$pattern_regex")
    if [ ! -z "$matched" ]; then
        FILES_TO_CHECK="$FILES_TO_CHECK
$matched"
    fi
done

FILES_TO_CHECK=$(echo "$FILES_TO_CHECK" | sort -u)

if [ -z "$FILES_TO_CHECK" ]; then
    echo "[$TIMESTAMP] No matching files in time range" >> "$LOG_FILE"
    exit 0
fi

# Download and delete files that don't exist locally
DOWNLOADED_COUNT=0
SKIPPED_COUNT=0
DELETED_COUNT=0

echo "$FILES_TO_CHECK" | while read -r filename; do
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
                
                # Delete the file from server after successful download
                DELETE_BATCH=$(mktemp)
                cat > "$DELETE_BATCH" << EOFDELETE
cd $REMOTE_DIR
rm $filename
bye
EOFDELETE
                
                sshpass -p "$REMOTE_PASSWORD" sftp -oBatchMode=no -o HostKeyAlgorithms=+ssh-rsa,ssh-dss -o PubkeyAcceptedKeyTypes=+ssh-rsa -b "$DELETE_BATCH" "$REMOTE_USER@$REMOTE_HOST" >> "$LOG_FILE" 2>&1
                
                if [ $? -eq 0 ]; then
                    echo "[$TIMESTAMP] Deleted from server: $filename" >> "$LOG_FILE"
                    DELETED_COUNT=$((DELETED_COUNT + 1))
                else
                    echo "[$TIMESTAMP] Failed to delete from server: $filename" >> "$LOG_FILE"
                fi
                
                rm -f "$DELETE_BATCH"
            fi
            
            rm -f "$DOWNLOAD_BATCH"
        fi
    fi
done

echo "[$TIMESTAMP] Download completed - Downloaded: $DOWNLOADED_COUNT, Skipped: $SKIPPED_COUNT, Deleted from server: $DELETED_COUNT" >> "$LOG_FILE"
