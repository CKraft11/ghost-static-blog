#!/bin/bash

# Check if the required tools are installed
command -v convert >/dev/null 2>&1 || { echo >&2 "ImageMagick is required but not installed. Aborting."; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || { echo >&2 "ffmpeg is required but not installed. Aborting."; exit 1; }
command -v parallel >/dev/null 2>&1 || { echo >&2 "GNU Parallel is required but not installed. Aborting."; exit 1; }

# Check if correct number of arguments is provided
if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Usage: $0 <directory> [--force]"
    exit 1
fi

# Set the input directory
input_dir="$1"
force_reconvert=false

# Check for --force option
if [ "$2" = "--force" ]; then
    force_reconvert=true
fi

# Function to check if a file is animated GIF
is_animated_gif() {
    local file="$1"
    [ "$(identify -format "%n" "$file" 2>/dev/null | grep -m1 -o '[0-9]*')" -gt 1 ]
}

# Function to convert a single file
convert_file() {
    local input_file="$1"
    local base_name="${input_file%.*}"
    local extension="${input_file##*.}"
    local converted=false

    # Convert to JXL if not already converted or force reconvert is true
    if [ ! -f "${base_name}.jxl" ] || $force_reconvert; then
        convert "$input_file" "${base_name}.jxl"
        converted=true
    fi

    # Convert to AVIF if not already converted or force reconvert is true
    if [ ! -f "${base_name}.avif" ] || $force_reconvert; then
        convert "$input_file" "${base_name}.avif"
        converted=true
    fi

    # Convert to WebP if not already converted or force reconvert is true
    if [ ! -f "${base_name}.webp" ] || $force_reconvert; then
        if [ "$extension" = "gif" ] && is_animated_gif "$input_file"; then
            ffmpeg -i "$input_file" -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -c:v libwebp -preset picture -loop 0 -compression_level 6 "${base_name}.webp" -y
        else
            convert "$input_file" "${base_name}.webp"
        fi
        converted=true
    fi

    if $converted; then
        echo "Converted: $input_file"
    else
        echo "Skipped (already converted): $input_file"
    fi

    # Update progress
    progress_file="/tmp/convert_progress"
    current=$(cat "$progress_file")
    echo $((current + 1)) > "$progress_file"
}

export -f convert_file
export -f is_animated_gif
export force_reconvert

# Count total number of files
total_files=$(find "$input_dir" -type f \( -iname "*.gif" -o -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" \) | wc -l)
echo "Total files to process: $total_files"

# Initialize progress file
echo 0 > /tmp/convert_progress

# Function to display progress
display_progress() {
    while true; do
        current=$(cat /tmp/convert_progress)
        percentage=$((current * 100 / total_files))
        printf "\rProgress: %d%% (%d/%d)" $percentage $current $total_files
        if [ $current -eq $total_files ]; then
            echo
            break
        fi
        sleep 1
    done
}

# Start progress display in background
display_progress &

# Find files and convert them in parallel
find "$input_dir" -type f \( -iname "*.gif" -o -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" \) -print0 | 
parallel -0 -j+0 convert_file

# Clean up
rm /tmp/convert_progress

echo "Conversion complete!"