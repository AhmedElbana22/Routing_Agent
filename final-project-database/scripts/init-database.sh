#!/bin/bash
set -euo pipefail

echo "Setting up database with PostGIS and pgRouting..."

# Source common database setup
source /usr/local/bin/common.sh

# Create extensions
psql -v ON_ERROR_STOP=1 <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS postgis;
    CREATE EXTENSION IF NOT EXISTS pgrouting;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS btree_gin;
EOSQL

echo "Extensions created successfully"

echo "Database setup complete!"