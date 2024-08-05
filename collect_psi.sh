#!/bin/bash
#
# This collects PSI (Pressure Stall Information) and writes it to a CSV file output file

set -eou pipefail

timestamp=$(date +"%Y%m%d_%H%M%S")
readonly OUTPUT_FILE="/$PWD/psi_log_$timestamp.csv"

echo "Writing to OUTPUT_FILE: $OUTPUT_FILE"

write_headers() {
    echo "Timestamp,CPU_Some,CPU_Full,Memory_Some,Memory_Full,IO_Some,IO_Full" > "$OUTPUT_FILE"
}

collect_psi_data() {
    local timestamp
    timestamp=$(date +"%Y-%m-%d %H:%M:%S")
    local cpu_data
    cpu_data=$(grep -E 'some|full' /proc/pressure/cpu | awk '{print $2}' | paste -sd "," -)
    local memory_data
    memory_data=$(grep -E 'some|full' /proc/pressure/memory | awk '{print $2}' | paste -sd "," -)
    local io_data
    io_data=$(grep -E 'some|full' /proc/pressure/io | awk '{print $2}' | paste -sd "," -)

    echo "$timestamp,$cpu_data,$memory_data,$io_data" >> "$OUTPUT_FILE"
}

write_headers

readonly INTERVAL=10
readonly DURATION=600
readonly ITERATIONS=$((DURATION / INTERVAL))
echo "Collecting PSI info every $INTERVAL seconds for $DURATION seconds in $ITERATIONS iterations"
for ((i=0; i<ITERATIONS; i++)); do
    collect_psi_data
    sleep $INTERVAL
done

echo "Done collecting PSI info"