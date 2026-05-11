CREATE TABLE IF NOT EXISTS gtfs_staging_agency (
    feed_id TEXT NOT NULL,
    agency_id TEXT NOT NULL,
    agency_name TEXT,
    agency_url TEXT,
    agency_timezone TEXT,
    imported_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (feed_id, agency_id)
);

CREATE TABLE IF NOT EXISTS gtfs_staging_calendar (
    feed_id TEXT NOT NULL,
    monday INTEGER,
    tuesday INTEGER,
    wednesday INTEGER,
    thursday INTEGER,
    friday INTEGER,
    saturday INTEGER,
    sunday INTEGER,
    start_date TEXT,
    end_date TEXT,
    service_id TEXT NOT NULL,
    imported_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (feed_id, service_id)
);

CREATE TABLE IF NOT EXISTS gtfs_staging_routes (
    feed_id TEXT NOT NULL,
    route_id TEXT NOT NULL,
    agency_id TEXT,
    route_long_name TEXT,
    route_short_name TEXT,
    route_type INTEGER,
    continuous_pickup INTEGER,
    continuous_drop_off INTEGER,
    route_short_name_ar TEXT,
    imported_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (feed_id, route_id)
);

CREATE TABLE IF NOT EXISTS gtfs_staging_stops (
    feed_id TEXT NOT NULL,
    stop_id TEXT NOT NULL,
    stop_name TEXT,
    stop_lat DOUBLE PRECISION,
    stop_lon DOUBLE PRECISION,
    stop_name_ar TEXT,
    imported_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (feed_id, stop_id)
);

CREATE TABLE IF NOT EXISTS gtfs_staging_trips (
    feed_id TEXT NOT NULL,
    route_id TEXT,
    service_id TEXT,
    trip_headsign TEXT,
    direction_id INTEGER,
    shape_id TEXT,
    trip_id TEXT NOT NULL,
    trip_headsign_ar TEXT,
    imported_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (feed_id, trip_id)
);

CREATE TABLE IF NOT EXISTS gtfs_staging_stop_times (
    feed_id TEXT NOT NULL,
    trip_id TEXT,
    stop_id TEXT,
    stop_sequence INTEGER,
    arrival_time TEXT,
    departure_time TEXT,
    timepoint INTEGER,
    imported_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (feed_id, trip_id, stop_sequence)
);

CREATE TABLE IF NOT EXISTS gtfs_staging_shapes (
    feed_id TEXT NOT NULL,
    shape_id TEXT,
    shape_pt_sequence INTEGER,
    shape_pt_lat DOUBLE PRECISION,
    shape_pt_lon DOUBLE PRECISION,
    imported_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (feed_id, shape_id, shape_pt_sequence)
);

CREATE TABLE IF NOT EXISTS gtfs_staging_feed_info (
    feed_id TEXT NOT NULL,
    feed_publisher_name TEXT,
    feed_publisher_url TEXT,
    feed_contact_url TEXT,
    feed_start_date TEXT,
    feed_end_date TEXT,
    feed_version TEXT NOT NULL,
    feed_lang TEXT,
    imported_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (feed_id, feed_version)
);

-- Helper Functions for Data Quality

-- Validate staging data quality
CREATE OR REPLACE FUNCTION gtfs_validate_staging_data() RETURNS TABLE(
        table_name TEXT,
        validation_rule TEXT,
        issue_count BIGINT
    ) LANGUAGE plpgsql AS $$ BEGIN

    -- Check for missing required fields in stops
    RETURN QUERY
    SELECT 'gtfs_staging_stops'::TEXT,
        'Missing stop_id'::TEXT,
        COUNT(*)
    FROM gtfs_staging_stops
    WHERE stop_id IS NULL
        OR stop_id = '';

    RETURN QUERY
    SELECT 'gtfs_staging_stops'::TEXT,
        'Missing coordinates'::TEXT,
        COUNT(*)
    FROM gtfs_staging_stops
    WHERE stop_lat IS NULL
        OR stop_lon IS NULL;

    -- Check for missing required fields in routes
    RETURN QUERY
    SELECT 'gtfs_staging_routes'::TEXT,
        'Missing route_id'::TEXT,
        COUNT(*)
    FROM gtfs_staging_routes
    WHERE route_id IS NULL
        OR route_id = '';

    -- Check for orphaned trips (route doesn't exist)
    RETURN QUERY
    SELECT 'gtfs_staging_trips'::TEXT,
        'Orphaned trips (no route)'::TEXT,
        COUNT(*)
    FROM gtfs_staging_trips t
        LEFT JOIN gtfs_staging_routes r ON t.route_id = r.route_id
    WHERE r.route_id IS NULL;

    -- Check for orphaned stop_times
    RETURN QUERY
    SELECT 'gtfs_staging_stop_times'::TEXT,
        'Orphaned stop_times (no trip)'::TEXT,
        COUNT(*)
    FROM gtfs_staging_stop_times st
        LEFT JOIN gtfs_staging_trips t ON st.trip_id = t.trip_id
    WHERE t.trip_id IS NULL;

END;
$$;

-- Get staging data statistics
CREATE OR REPLACE FUNCTION gtfs_staging_stats() RETURNS TABLE(
        table_name TEXT,
        record_count BIGINT,
        latest_import TIMESTAMPTZ
    ) LANGUAGE plpgsql AS $$ BEGIN

    RETURN QUERY
    SELECT 'gtfs_staging_agency'::TEXT,
        COUNT(*),
        MAX(imported_at)
    FROM gtfs_staging_agency;

    RETURN QUERY
    SELECT 'gtfs_staging_routes'::TEXT,
        COUNT(*),
        MAX(imported_at)
    FROM gtfs_staging_routes;

    RETURN QUERY
    SELECT 'gtfs_staging_stops'::TEXT,
        COUNT(*),
        MAX(imported_at)
    FROM gtfs_staging_stops;

    RETURN QUERY
    SELECT 'gtfs_staging_trips'::TEXT,
        COUNT(*),
        MAX(imported_at)
    FROM gtfs_staging_trips;

    RETURN QUERY
    SELECT 'gtfs_staging_stop_times'::TEXT,
        COUNT(*),
        MAX(imported_at)
    FROM gtfs_staging_stop_times;

    RETURN QUERY
    SELECT 'gtfs_staging_shapes'::TEXT,
        COUNT(*),
        MAX(imported_at)
    FROM gtfs_staging_shapes;

END;
$$;

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_staging_routes_id ON gtfs_staging_routes(route_id);
CREATE INDEX IF NOT EXISTS idx_staging_stops_id ON gtfs_staging_stops(stop_id);
CREATE INDEX IF NOT EXISTS idx_staging_trips_id ON gtfs_staging_trips(trip_id);
CREATE INDEX IF NOT EXISTS idx_staging_trips_route ON gtfs_staging_trips(route_id);
CREATE INDEX IF NOT EXISTS idx_staging_stop_times_trip ON gtfs_staging_stop_times(trip_id);
CREATE INDEX IF NOT EXISTS idx_staging_stop_times_stop ON gtfs_staging_stop_times(stop_id);
CREATE INDEX IF NOT EXISTS idx_staging_shapes_id ON gtfs_staging_shapes(shape_id);