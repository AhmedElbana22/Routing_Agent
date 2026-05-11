# Transport Database - PostgreSQL 18 + PostGIS + GTFS

A PostgreSQL 18 database with PostGIS 3.6 and pgRouting for managing public transportation data with GTFS (General Transit Feed Specification) support.

## Project Structure

```
.
├── Dockerfile                 # Database container definition
├── docker-compose.yml         # Multi-container orchestration
├── .dockerignore             # Docker build exclusions
│
├── sql/                       # SQL schemas and functions
│   ├── schema.sql            # Operational transport schema
│   ├── gtfs-staging-schema.sql   # GTFS staging tables
│   └── gtfs-etl-transform.sql    # ETL transformation functions
│
├── scripts/                   # Shell scripts
│   ├── common.sh             # Shared database connection setup
│   ├── init-database.sh      # Initialize PostgreSQL extensions
│   ├── init-gtfs.sh          # GTFS initialization
│   ├── gtfs2db.sh            # Import GTFS data to staging
│   ├── gtfs-etl.sh           # Run ETL transformation
│   └── test-deployment.sh    # Deployment verification
│
└── gtfs-data/                 # GTFS CSV files
    ├── agency.csv
    ├── routes.csv
    ├── stops.csv
    ├── trips.csv
    ├── stop_times.csv
    ├── shapes.csv
    ├── calendar.csv
    └── feed_info.csv
```

## Quick Start

### 1. Start the Database

```bash
docker compose up -d --build
```

Wait ~45 seconds for initialization to complete.

### 2. Verify Deployment

```bash
./scripts/test-deployment.sh
```

### 3. Access pgAdmin

Open http://localhost:8080

- **Email**: admin@example.com
- **Password**: admin

Add server connection:

- **Host**: transport-db
- **Port**: 5432
- **Database**: transport_db
- **Username**: postgres
- **Password**: postgres

## Database Schema

### Operational Tables

- **`route`** - Transport routes (buses, microbuses, etc.)
- **`stop`** - Stop locations with PostGIS geometries
- **`route_geometry`** - Route line geometries (WGS84 + projected)
- **`route_stop`** - Stops along each route with sequences

### GTFS Staging Tables

- **`gtfs_staging_agency`** - Transit agencies
- **`gtfs_staging_routes`** - Route definitions
- **`gtfs_staging_stops`** - Stop locations
- **`gtfs_staging_trips`** - Individual trips
- **`gtfs_staging_stop_times`** - Stop times per trip
- **`gtfs_staging_shapes`** - Route geometries
- **`gtfs_staging_calendar`** - Service calendars
- **`gtfs_staging_feed_info`** - Feed metadata

## GTFS Data Management

### Import GTFS Data

```bash
# Import to staging only
docker exec transport-db gtfs2db.sh

# Import + run ETL transformation
docker exec transport-db gtfs2db.sh --with-etl
```

### Run ETL Manually

```bash
docker exec transport-db gtfs-etl.sh
```

### Check GTFS Import Status

```sql
SELECT * FROM gtfs_staging_stats();
SELECT * FROM gtfs_validate_staging_data();
SELECT * FROM gtfs_etl_log ORDER BY etl_id DESC LIMIT 5;
```

## Common Tasks

### Connect to Database

```bash
# Using psql
docker exec -it transport-db psql -U postgres -d transport_db

# From host (if psql installed)
psql -h localhost -U postgres -d transport_db
```

### View Data

```sql
-- Count routes by mode
SELECT mode, COUNT(*) FROM route GROUP BY mode;

-- Find stops near a location
SELECT stop_id, name,
       ST_Distance(geom_22992,
                   ST_Transform(ST_SetSRID(ST_MakePoint(29.9661, 31.2469), 4326), 22992)
       ) AS distance_m
FROM stop
ORDER BY distance_m
LIMIT 5;

-- Routes passing through a stop
SELECT r.name, r.mode, rs.stop_sequence
FROM route_stop rs
JOIN route r ON rs.route_id = r.route_id
WHERE rs.stop_id = (SELECT stop_id FROM stop WHERE name ILIKE '%san stefano%' LIMIT 1)
ORDER BY r.name;
```

### Import New GTFS Feed

```bash
# 1. Copy new GTFS files to container
docker cp ./new-gtfs-data/. transport-db:/gtfs-data/

# 2. Import and transform
docker exec transport-db gtfs2db.sh --with-etl
```

### Backup Database

```bash
docker exec transport-db pg_dump -U postgres transport_db > backup.sql
```

### Restore Database

```bash
cat backup.sql | docker exec -i transport-db psql -U postgres -d transport_db
```

## Architecture

### Data Flow

```
GTFS CSV Files
     ↓
[gtfs2db.sh] → GTFS Staging Tables (raw data, preserved)
     ↓
[ETL Transform] → Operational Schema (normalized, with PostGIS)
     ↓
Application Queries
```

### Key Features

- **UPSERT Pattern**: Updates existing data, preserves history in staging
- **Multi-Feed Support**: Import multiple GTFS datasets safely
- **PostGIS Integration**: Spatial queries and routing ready
- **pgRouting Ready**: Street network analysis capable
- **ETL Logging**: Track all transformations with timestamps

## Extensions Installed

- **PostGIS 3.6** - Spatial database capabilities
- **pgRouting** - Routing and network analysis
- **pg_trgm** - Fuzzy text search
- **btree_gin** - GIN indexes on scalar types

## Environment Variables

- `POSTGRES_DB` - Database name (default: transport_db)
- `POSTGRES_USER` - Database user (default: postgres)
- `POSTGRES_PASSWORD` - Database password (default: postgres)

## Troubleshooting

### Container won't start

```bash
docker logs transport-db
```

### GTFS data not importing

```bash
# Check if files exist
docker exec transport-db ls -lh /gtfs-data/

# Check staging tables
docker exec transport-db psql -U postgres -d transport_db -c "SELECT * FROM gtfs_staging_stats();"
```

### ETL failures

```sql
SELECT * FROM gtfs_etl_log WHERE status = 'failed';
```

## Development

### Rebuild After Changes

```bash
docker compose down -v
docker compose up -d --build
```

### Run Tests

```bash
./scripts/test-deployment.sh
```

## License

MIT

## Contributors

Marwan
