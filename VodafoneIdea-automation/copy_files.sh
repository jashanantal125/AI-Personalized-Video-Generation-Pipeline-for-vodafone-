#!/bin/bash

SOURCE_DIR=~/vicode/VodafoneIdea/vi_server_files
DEST_DIR=~/vicode/VodafoneIdea/boat_nov4_extract

# Start and end timestamps
START="2025_11_04_00_00"
END="2025_11_04_18_24"

# Copy files in range
for file in "$SOURCE_DIR"/BOAT_2025_11_04_*.csv; do
    filename=$(basename "$file")
    # Extract timestamp from filename (BOAT_2025_11_04_HH_MM_SS.csv)
    timestamp=$(echo "$filename" | sed 's/BOAT_\(.*\)_[0-9][0-9]\.csv/\1/')
    
    # Compare timestamps
    if [[ "$timestamp" >= "$START" && "$timestamp" <= "$END" ]]; then
        cp "$file" "$DEST_DIR/"
        echo "Copied: $filename"
    fi
done

echo "Copy completed!"
