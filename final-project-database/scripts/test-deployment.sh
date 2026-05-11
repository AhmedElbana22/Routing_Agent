#!/usr/bin/env bash
set -euo pipefail

echo "=========================================="
echo "Transport Database Deployment Test"
echo "=========================================="
echo ""

#!/bin/bash
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Test functions
test_pass() {
    echo -e "${GREEN}âœ“${NC} $1"
}

test_fail() {
    echo -e "${RED}âœ—${NC} $1"
}

test_warn() {
    echo -e "${YELLOW}âš ${NC} $1"
}

# Check if container is running
echo "1. Checking if transport-db container is running..."
if docker ps | grep -q transport-db; then
    test_pass "Container is running"
else
    test_fail "Container is NOT running"
    echo "  Run: docker-compose up -d --build"
    exit 1
fi

echo ""
echo "2. Checking PostgreSQL connection..."
if docker exec transport-db psql -U postgres -d transport_db -c "SELECT version();" > /dev/null 2>&1; then
    test_pass "PostgreSQL connection successful"
    VERSION=$(docker exec transport-db psql -U postgres -d transport_db -t -c "SELECT version();" | head -n1)
    echo "  $VERSION"
else
    test_fail "Cannot connect to PostgreSQL"
    exit 1
fi

echo ""
echo "3. Checking extensions..."
EXTENSIONS=$(docker exec transport-db psql -U postgres -d transport_db -t -c "\dx" | grep -E "postgis|pgrouting|pg_trgm|btree_gin" | wc -l)
if [ "$EXTENSIONS" -ge 4 ]; then
    test_pass "All required extensions installed ($EXTENSIONS/4)"
else
    test_fail "Missing extensions (found $EXTENSIONS/4)"
fi

echo ""
echo "4. Checking operational schema tables..."
for table in route stop route_geometry route_stop; do
    if docker exec transport-db psql -U postgres -d transport_db -t -c "SELECT COUNT(*) FROM \"$table\";" > /dev/null 2>&1; then
        COUNT=$(docker exec transport-db psql -U postgres -d transport_db -t -c "SELECT COUNT(*) FROM \"$table\";" | tr -d ' ')
        test_pass "Table '$table' exists ($COUNT rows)"
    else
        test_fail "Table '$table' missing"
    fi
done

echo ""
echo "5. Checking GTFS staging tables..."
STAGING_TABLES=0
for table in gtfs_staging_agency gtfs_staging_calendar gtfs_staging_routes gtfs_staging_stops gtfs_staging_trips gtfs_staging_stop_times gtfs_staging_shapes gtfs_staging_feed_info; do
    if docker exec transport-db psql -U postgres -d transport_db -t -c "SELECT COUNT(*) FROM $table;" > /dev/null 2>&1; then
        STAGING_TABLES=$((STAGING_TABLES + 1))
    fi
done

if [ "$STAGING_TABLES" -eq 8 ]; then
    test_pass "All GTFS staging tables created (8/8)"
else
    test_warn "Missing GTFS staging tables ($STAGING_TABLES/8)"
fi

echo ""
echo "6. Checking GTFS ETL functions..."
if docker exec transport-db psql -U postgres -d transport_db -t -c "SELECT proname FROM pg_proc WHERE proname = 'gtfs_etl_to_operational';" | grep -q gtfs_etl_to_operational; then
    test_pass "GTFS ETL function exists"
else
    test_fail "GTFS ETL function missing"
fi

echo ""
echo "7. Checking GTFS data import..."
ROUTES_STAGING=$(docker exec transport-db psql -U postgres -d transport_db -t -c "SELECT COUNT(*) FROM gtfs_staging_routes;" 2>/dev/null | tr -d ' ' || echo "0")
STOPS_STAGING=$(docker exec transport-db psql -U postgres -d transport_db -t -c "SELECT COUNT(*) FROM gtfs_staging_stops;" 2>/dev/null | tr -d ' ' || echo "0")

if [ "$ROUTES_STAGING" -gt 0 ]; then
    test_pass "GTFS routes imported to staging ($ROUTES_STAGING routes)"
else
    test_warn "No GTFS routes in staging"
fi

if [ "$STOPS_STAGING" -gt 0 ]; then
    test_pass "GTFS stops imported to staging ($STOPS_STAGING stops)"
else
    test_warn "No GTFS stops in staging"
fi

echo ""
echo "8. Checking operational data (after ETL)..."
ROUTES_OP=$(docker exec transport-db psql -U postgres -d transport_db -t -c "SELECT COUNT(*) FROM \"route\";" 2>/dev/null | tr -d ' ' || echo "0")
STOPS_OP=$(docker exec transport-db psql -U postgres -d transport_db -t -c "SELECT COUNT(*) FROM \"stop\";" 2>/dev/null | tr -d ' ' || echo "0")

if [ "$ROUTES_OP" -gt 0 ]; then
    test_pass "Routes in operational schema ($ROUTES_OP routes)"
else
    test_warn "No routes in operational schema (ETL may not have run)"
fi

if [ "$STOPS_OP" -gt 0 ]; then
    test_pass "Stops in operational schema ($STOPS_OP stops)"
else
    test_warn "No stops in operational schema (ETL may not have run)"
fi

echo ""
echo "=========================================="
echo "Deployment Test Complete!"
echo "=========================================="
