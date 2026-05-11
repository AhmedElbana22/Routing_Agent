-- 1) route table
CREATE TABLE IF NOT EXISTS "route" (
    route_id BIGSERIAL PRIMARY KEY,
    feed_id TEXT,
    -- GTFS feed identifier for multi-feed support
    gtfs_route_id TEXT,
    -- original GTFS route_id for reference
    name TEXT NOT NULL,
    -- name for the transport ex: victoria - sidi gaber microbus
    continuous_pickup BOOLEAN NOT NULL DEFAULT true,
    -- GTFS: 0=allowed, 1=not allowed (stored as true=allowed)
    continuous_drop_off BOOLEAN NOT NULL DEFAULT true,
    -- GTFS: 0=allowed, 1=not allowed (stored as true = allowed)
    mode TEXT,
    -- ex : microbus, bus, tram
    cost INTEGER NOT NULL,
    -- in piasters, 100 piasters = 1 pound
    one_way BOOLEAN NOT NULL DEFAULT true,
    operator TEXT,
    -- ex : independant, goverment, company
    attrs JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (feed_id, gtfs_route_id)
);
CREATE INDEX IF NOT EXISTS idx_gtfs_route_id ON "route"(gtfs_route_id);
CREATE INDEX IF NOT EXISTS idx_route_continuous_pickup ON "route"(continuous_pickup);
CREATE INDEX IF NOT EXISTS idx_route_continuous_drop_off ON "route"(continuous_drop_off);
CREATE INDEX IF NOT EXISTS idx_route_attrs_gin ON "route" USING GIN (attrs);
-- 2) route_geometry table
CREATE TABLE IF NOT EXISTS route_geometry (
    route_geom_id BIGSERIAL PRIMARY KEY,
    route_id BIGINT NOT NULL REFERENCES "route"(route_id) ON DELETE CASCADE,
    geom_4326 geometry(LineString, 4326) NOT NULL,
    -- real geographical WGS84 storage
    geom_22992 geometry(LineString, 22992),
    -- projected copy in 22992(egypt red belt) in (meters) for fast queries
    attrs JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);
-- indexes for route_geometry
CREATE INDEX IF NOT EXISTS idx_route_geometry_geom_22992_gist ON route_geometry USING GIST (geom_22992);
CREATE INDEX IF NOT EXISTS idx_route_geometry_routeid ON route_geometry (route_id);
CREATE INDEX IF NOT EXISTS idx_route_geometry_attrs_gin ON route_geometry USING GIN (attrs);
-- trigger: populate geom_22992 from geom_4326 on insert
CREATE OR REPLACE FUNCTION trg_route_geometry_sync_proj() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.geom_4326 IS NOT NULL THEN NEW.geom_4326 := ST_SetSRID(NEW.geom_4326, 4326);
NEW.geom_22992 := ST_Transform(NEW.geom_4326, 22992);
ELSE NEW.geom_22992 := NULL;
END IF;
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS route_geometry_sync_proj ON route_geometry;
CREATE TRIGGER route_geometry_sync_proj BEFORE
INSERT ON route_geometry FOR EACH ROW EXECUTE FUNCTION trg_route_geometry_sync_proj();
-- 3) trip table - represents specific scheduled trips on a route
CREATE TABLE IF NOT EXISTS trip (
    trip_id BIGSERIAL PRIMARY KEY,
    route_id BIGINT NOT NULL REFERENCES "route"(route_id) ON DELETE CASCADE,
    feed_id TEXT,
    gtfs_trip_id TEXT,
    -- original GTFS trip_id
    route_geom_id BIGINT REFERENCES route_geometry(route_geom_id) ON DELETE
    SET NULL,
        headsign TEXT,
        -- destination sign, ex: "Raml Station"
        direction_id SMALLINT,
        -- 0 or 1 for opposite directions
        service_id TEXT,
        -- links to calendar/service patterns
        attrs JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE (feed_id, gtfs_trip_id)
);
CREATE INDEX IF NOT EXISTS idx_trip_route_id ON trip(route_id);
CREATE INDEX IF NOT EXISTS idx_trip_id_gtfs ON trip(gtfs_trip_id);
CREATE INDEX IF NOT EXISTS idx_trip_route_geom_id ON trip(route_geom_id);
CREATE INDEX IF NOT EXISTS idx_trip_attrs_gin ON trip USING GIN (attrs);
-- 4) stop table; The stop itself ex: san stefano station
CREATE TABLE IF NOT EXISTS "stop" (
    stop_id BIGSERIAL PRIMARY KEY,
    feed_id TEXT,
    -- GTFS feed identifier
    gtfs_stop_id TEXT,
    -- original GTFS stop_id for reference
    name TEXT,
    -- full name for the stop ex: alexandria raml tram station
    UNIQUE (feed_id, gtfs_stop_id),
    geom_4326 geometry(Point, 4326) NOT NULL,
    -- geographical real location
    geom_22992 geometry(Point, 22992),
    -- egypt red belt (22992) projection
    attrs JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);
-- Indexes for stops table
CREATE INDEX IF NOT EXISTS idx_stop_geom_22992_spgist ON "stop" USING SPGIST (geom_22992);
CREATE INDEX IF NOT EXISTS idx_stop_attrs_gin ON "stop" USING GIN (attrs);
CREATE INDEX IF NOT EXISTS idx_stop_name ON "stop" (name);
-- trigger for syncing projected stop geometry
CREATE OR REPLACE FUNCTION trg_stop_sync_proj() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.geom_4326 IS NOT NULL THEN NEW.geom_4326 := ST_SetSRID(NEW.geom_4326, 4326);
NEW.geom_22992 := ST_Transform(NEW.geom_4326, 22992);
ELSE NEW.geom_22992 := NULL;
END IF;
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS stop_sync_proj ON "stop";
CREATE TRIGGER stop_sync_proj BEFORE
INSERT ON "stop" FOR EACH ROW EXECUTE FUNCTION trg_stop_sync_proj();
-- 5) route_stop, actual stop in trip ex : san stefano station trip 1
CREATE TABLE IF NOT EXISTS route_stop (
    route_stop_id BIGSERIAL PRIMARY KEY,
    trip_id BIGINT NOT NULL REFERENCES trip(trip_id) ON DELETE CASCADE,
    stop_id BIGINT NOT NULL REFERENCES "stop"(stop_id) ON DELETE CASCADE,
    stop_sequence INTEGER NOT NULL,
    -- the numbering of the stop in the trip, ex : san stefano: 1, ganaklis: 2
    arrival_time TIME,
    departure_time TIME,
    attrs JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (trip_id, stop_sequence)
);
-- Indexes for route stops table
CREATE INDEX IF NOT EXISTS idx_route_stop_tripid_seq ON route_stop (trip_id, stop_sequence);
CREATE INDEX IF NOT EXISTS idx_route_stop_stopid ON route_stop (stop_id);
CREATE INDEX IF NOT EXISTS idx_route_stop_attrs_gin ON route_stop USING GIN (attrs);