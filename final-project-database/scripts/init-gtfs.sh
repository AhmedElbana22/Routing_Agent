#!/bin/bash
set -euo pipefail

echo "====  GTFS init starting ===="

# Source common database setup
source /usr/local/bin/common.sh

# Check if GTFS data directory exists and has files
if [ -d "/gtfs-data" ] && [ -n "$(ls -A /gtfs-data 2>/dev/null)" ]; then
    echo "GTFS data found in /gtfs-data, starting import..."

    # Run GTFS import and ETL
    /usr/local/bin/gtfs2db.sh

    echo "==== GTFS import and ETL completed! ===="
else
    echo "WARNING: No GTFS data found in /gtfs-data — skipping import."
    echo "You can add GTFS CSV files later and run: gtfs2db.sh"
fi