# Source common database setup
source /usr/local/bin/common.sh

# Default: clear staging after ETL (one-time run)
CLEAR_STAGING=true
if [[ "${1:-}" == "--keep-staging" ]]; then
    CLEAR_STAGING=false
fi

# Run ETL function
echo "Running ETL transformation..."
${PSQL} <<-SQL
    SELECT gtfs_etl_to_operational(${CLEAR_STAGING});
SQL

echo
echo "Operational data summary:"
${PSQL} <<-SQL
    SELECT 'routes' AS table, COUNT(*) AS count FROM "route"
    UNION ALL
    SELECT 'stops', COUNT(*) FROM "stop"
    UNION ALL
    SELECT 'route_geometries', COUNT(*) FROM route_geometry
    UNION ALL
    SELECT 'route_stops', COUNT(*) FROM route_stop;
SQL

echo
echo "==== GTFS ETL Transformation completed ===="
