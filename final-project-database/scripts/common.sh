#!/bin/bash
# Exit on error
set -euo pipefail

# PostgreSQL connection settings
export PGPORT=5432
export PGUSER="${POSTGRES_USER:-postgres}"
export PGDATABASE="${POSTGRES_DB:-transport_db}"
export PGPASSWORD="${POSTGRES_PASSWORD:-postgres}"

# Database connection details
DB_HOST="localhost"
DB_PORT="$PGPORT"
DB_NAME="$PGDATABASE"
DB_USER="$PGUSER"

# psql command with standard options
PSQL="psql -h ${DB_HOST} -p ${DB_PORT} -U ${DB_USER} -d ${DB_NAME} -v ON_ERROR_STOP=1 --quiet"

# Default GTFS data directory
GTFS_DIR="${GTFS_DIR:-/gtfs-data}"