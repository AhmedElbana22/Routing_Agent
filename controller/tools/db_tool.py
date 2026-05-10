"""
db_tool.py
Direct PostgreSQL queries for info_request intents.

Handles:
  - Fare estimation  : route.cost (baseline) + price_predictor.py (ML model)
  - Schedule info    : trip + route_stop tables
  - Line info        : route + trip + stop tables
  - Stop info        : stop table (name, coords, Arabic name from attrs)

Architecture:
  Queries PostgreSQL DIRECTLY (same pattern as geo_tool.py).
  No external DB API exists — we own the DB.

DB schema used:
  route       : route_id, gtfs_route_id, name, mode, cost, operator, attrs
  trip        : trip_id, route_id, headsign, service_id, direction_id, attrs
  route_stop  : route_stop_id, trip_id, stop_id, stop_sequence,
                arrival_time, departure_time
  stop        : stop_id, name, geom_4326, attrs

Arabic fields live in JSONB attrs:
  route.attrs ->>'route_short_name_ar'
  trip.attrs  ->>'headsign_ar'
  stop.attrs  ->>'name_ar'
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from config import settings
from model.intent.schema import (
    FareEstimate,
    RouteRecord,
    RouteStopRecord,
    StopRecord,
    TripRecord,
)
import structlog

logger = structlog.get_logger(__name__)

 
# DB connection (reuse same pattern as geo_tool.py) 


class DBPool:
    """
    Minimal psycopg2 connection wrapper with auto-reconnect.
    Same pattern as geo_tool.py — single persistent connection.
    """

    def __init__(self):
        self._conn = None

    def _connect(self) -> None:
        self._conn = psycopg2.connect(settings.db.dsn)
        self._conn.autocommit = True
        logger.info("db_tool_connected", host=settings.db.host, db=settings.db.db)

    def get_connection(self):
        try:
            if self._conn is None or self._conn.closed:
                self._connect()
            else:
                with self._conn.cursor() as cur:
                    cur.execute("SELECT 1")
            return self._conn
        except Exception:
            self._connect()
            return self._conn


_db_pool = DBPool()

 
# Fare predictor loader 


def _load_fare_predictor():
    """
    Lazy-load TripPricePredictor from model/fare/.
    Returns predictor instance or None if model not available.
    """
    try:
        from model.fare.price_predictor import TripPricePredictor   
        predictor = TripPricePredictor()                            
        logger.info(
            "fare_predictor_loaded",
            source=settings.fare.model_source,
            path=settings.fare.model_path,
            coefficients=predictor.coefficients,  
        )
        return predictor
    except FileNotFoundError as e:
        logger.warning("fare_model_file_missing", error=str(e))
        return None
    except Exception as e:
        logger.warning("fare_predictor_unavailable", error=str(e))
        return None


def _fetch_route_distance_meters(route_id: Any) -> Optional[float]:
    """
    Compute route distance in METERS from route_geometry.geom_4326.

    Uses PostGIS ST_Length with ::geography cast for accurate
    spherical distance (not planar).

    Returns distance in meters, or None if no geometry found.
    """
    sql = """
        SELECT
            ST_Length(geom_4326::geography) AS distance_meters
        FROM route_geometry
        WHERE route_id = %(route_id)s
        LIMIT 1;
    """
    try:
        conn = _db_pool.get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, {"route_id": route_id})
            row = cur.fetchone()

        if row and row["distance_meters"] is not None:
            return float(row["distance_meters"])

    except Exception as e:
        logger.error(
            "fetch_route_distance_failed",
            route_id=route_id,
            error=str(e),
        )

    return None

_fare_predictor = None   


def _get_fare_predictor():
    """Return cached predictor, loading it on first call."""
    global _fare_predictor
    if _fare_predictor is None:
        _fare_predictor = _load_fare_predictor()
    return _fare_predictor

 
# Raw SQL query helpers 


def _fetch_route_by_gtfs_id(gtfs_route_id: str) -> Optional[RouteRecord]:
    """
    Fetch route by GTFS route_id (the original ID from GTFS data).

    Uses gtfs_route_id column (not internal route_id PK).

    Example:
      gtfs_route_id = "I46ZQc9g0OMvTpnnq0RXs"
    """
    sql = """
        SELECT
            route_id,
            feed_id,
            gtfs_route_id,
            name,
            mode,
            cost,
            operator,
            one_way,
            continuous_pickup,
            continuous_drop_off,
            attrs
        FROM route
        WHERE gtfs_route_id = %(gtfs_route_id)s
        LIMIT 1;
    """
    try:
        conn = _db_pool.get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, {"gtfs_route_id": gtfs_route_id})
            row = cur.fetchone()

        if row:
            return RouteRecord(
                route_id=row["route_id"],
                feed_id=row["feed_id"],
                gtfs_route_id=row["gtfs_route_id"],
                name=row["name"],
                mode=row["mode"],
                cost=float(row["cost"]) if row["cost"] is not None else None,
                operator=row["operator"],
                one_way=row["one_way"],
                continuous_pickup=row["continuous_pickup"],
                continuous_drop_off=row["continuous_drop_off"],
                attrs=dict(row["attrs"]) if row["attrs"] else {},
            )
    except Exception as e:
        logger.error("fetch_route_failed", gtfs_route_id=gtfs_route_id, error=str(e))

    return None



def _fetch_route_by_internal_id(route_id: Any) -> Optional[RouteRecord]:
    """
    Fetch route by internal route_id PK.
    Used when we already have the internal ID from a join.
    """
    sql = """
        SELECT
            route_id,
            feed_id,
            gtfs_route_id,
            name,
            mode,
            cost,
            operator,
            one_way,
            continuous_pickup,
            continuous_drop_off,
            attrs
        FROM route
        WHERE route_id = %(route_id)s
        LIMIT 1;
    """
    try:
        conn = _db_pool.get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, {"route_id": route_id})
            row = cur.fetchone()

        if row:
            return RouteRecord(
                route_id=row["route_id"],
                feed_id=row["feed_id"],
                gtfs_route_id=row["gtfs_route_id"],
                name=row["name"],
                mode=row["mode"],
                cost=float(row["cost"]) if row["cost"] is not None else None,
                operator=row["operator"],
                one_way=row["one_way"],
                continuous_pickup=row["continuous_pickup"],
                continuous_drop_off=row["continuous_drop_off"],
                attrs=dict(row["attrs"]) if row["attrs"] else {},
            )
    except Exception as e:
        logger.error("fetch_route_by_id_failed", route_id=route_id, error=str(e))

    return None


def _fetch_trips_for_route(route_id: Any) -> List[TripRecord]:
    """
    Fetch all trips for a given route (internal route_id).

    Returns list of TripRecord — one per direction/service combo.
    """
    sql = """
        SELECT
            trip_id,
            route_id,
            feed_id,
            gtfs_trip_id,
            route_geom_id,
            headsign,
            direction_id,
            service_id,
            attrs
        FROM trip
        WHERE route_id = %(route_id)s
        ORDER BY direction_id ASC, trip_id ASC;
    """
    try:
        conn = _db_pool.get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, {"route_id": route_id})
            rows = cur.fetchall()

        return [
            TripRecord(
                trip_id=row["trip_id"],
                route_id=row["route_id"],
                feed_id=row["feed_id"],
                gtfs_trip_id=row["gtfs_trip_id"],
                route_geom_id=row["route_geom_id"],
                headsign=row["headsign"],
                direction_id=row["direction_id"],
                service_id=row["service_id"],
                attrs=dict(row["attrs"]) if row["attrs"] else {},
            )
            for row in rows
        ]
    except Exception as e:
        logger.error("fetch_trips_failed", route_id=route_id, error=str(e))

    return []


def _fetch_stops_for_trip(trip_id: Any) -> List[Dict[str, Any]]:
    """
    Fetch ordered stops for a trip with timing info.

    Joins route_stop → stop to get stop names + coordinates.
    Returns list of dicts with stop info + arrival/departure times.
    """
    sql = """
        SELECT
            rs.route_stop_id,
            rs.stop_sequence,
            rs.arrival_time,
            rs.departure_time,
            s.stop_id,
            s.gtfs_stop_id,
            s.name                    AS stop_name,
            s.attrs                   AS stop_attrs,
            ST_Y(s.geom_4326)         AS lat,
            ST_X(s.geom_4326)         AS lon
        FROM route_stop rs
        JOIN stop s ON s.stop_id = rs.stop_id
        WHERE rs.trip_id = %(trip_id)s
        ORDER BY rs.stop_sequence ASC;
    """
    try:
        conn = _db_pool.get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, {"trip_id": trip_id})
            rows = cur.fetchall()

        results = []
        for row in rows:
            stop_attrs = dict(row["stop_attrs"]) if row["stop_attrs"] else {}
            results.append({
                "route_stop_id":  row["route_stop_id"],
                "stop_sequence":  row["stop_sequence"],
                "arrival_time":   row["arrival_time"],
                "departure_time": row["departure_time"],
                "stop_id":        row["stop_id"],
                "gtfs_stop_id":   row["gtfs_stop_id"],
                "stop_name":      row["stop_name"],
                "stop_name_ar":   stop_attrs.get("name_ar"),
                "lat":            row["lat"],
                "lon":            row["lon"],
            })
        return results

    except Exception as e:
        logger.error("fetch_stops_for_trip_failed", trip_id=trip_id, error=str(e))

    return []


def _fetch_first_last_departure(route_id: Any) -> Dict[str, Optional[str]]:
    """
    Get the earliest arrival_time and latest departure_time
    across all stops for all trips on a route.

    Used to answer "what time does line X run?" queries.
    """
    sql = """
        SELECT
            MIN(rs.arrival_time)   AS first_arrival,
            MAX(rs.departure_time) AS last_departure
        FROM route_stop rs
        JOIN trip t ON t.trip_id = rs.trip_id
        WHERE t.route_id = %(route_id)s
          AND rs.arrival_time IS NOT NULL;
    """
    try:
        conn = _db_pool.get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, {"route_id": route_id})
            row = cur.fetchone()

        if row:
            return {
                "first_arrival":   str(row["first_arrival"])  if row["first_arrival"]  else None,
                "last_departure":  str(row["last_departure"]) if row["last_departure"] else None,
            }
    except Exception as e:
        logger.error("fetch_schedule_times_failed", route_id=route_id, error=str(e))

    return {"first_arrival": None, "last_departure": None}

 

# Main DBTool class 


class DBTool:
    """
    Handles all info_request queries against the transport database.

    Direct PostgreSQL access — no external API.
    Uses same DBPool pattern as geo_tool.py.

    Three main query types:
      get_fare()     → route.cost + ML model prediction
      get_schedule() → trip + route_stop timing info
      get_line_info()→ full route + trips + stops summary
    """


    #  Fare

    def get_fare(self, line_id: str) -> Optional[FareEstimate]:
        """
        Estimate fare for a route.

        Pipeline:
          1. Fetch route from DB → get route.cost (baseline) + mode
          2. Fetch route distance from route_geometry (ST_Length)
          3. Call TripPricePredictor.predict_for_mode(distance, mode)
          4. Fallback to route.cost if model/distance unavailable

        Args:
            line_id: GTFS route_id string
                     e.g. "I46ZQc9g0OMvTpnnq0RXs"

        Returns:
            FareEstimate with estimated_fare in EGP, or None.
        """
        route = _fetch_route_by_gtfs_id(line_id)
        if route is None:
            logger.warning("get_fare_route_not_found", line_id=line_id)
            return None

        baseline_cost = route.cost

        # Fetch distance from route_geometry 
        distance_meters = _fetch_route_distance_meters(route.route_id)

        # Try ML model prediction
        predictor = _get_fare_predictor()
        if predictor is not None and distance_meters is not None:
            try:
                predicted_fare = predictor.predict_for_mode(
                    distance=distance_meters,
                    mode=route.mode,        # uses MODE_DEFAULT_PASSENGERS
                )

                input_features = {
                    "distance_meters": distance_meters,
                    "mode":            route.mode,
                    "passengers":      None,   # resolved inside predict_for_mode
                }

                logger.info(
                    "fare_ml_predicted",
                    line_id=line_id,
                    route_name=route.name,
                    mode=route.mode,
                    distance_m=round(distance_meters, 1),
                    baseline=baseline_cost,
                    predicted=predicted_fare,
                )
                return FareEstimate(
                    route_id=route.route_id,
                    baseline_cost=baseline_cost,
                    estimated_fare=float(predicted_fare),
                    fare_basis="ml_predicted",
                    input_features=input_features,
                )
            except Exception as e:
                logger.warning(
                    "fare_ml_failed_using_baseline",
                    error=str(e),
                    line_id=line_id,
                )

        # Fallback 1: route.cost  
        if baseline_cost is not None:
            logger.info(
                "fare_fallback_baseline",
                line_id=line_id,
                cost=baseline_cost,
                reason="no_distance" if distance_meters is None else "no_predictor",
            )
            return FareEstimate(
                route_id=route.route_id,
                baseline_cost=baseline_cost,
                estimated_fare=baseline_cost,
                fare_basis="fixed",
            )

        # Fallback 2: no data 
        logger.warning("fare_no_data", line_id=line_id)
        return None

    # Schedule 

    def get_schedule(self, line_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch schedule info for a route.

        Returns:
          {
            "route_name":       "Asafra - Sidi Bishr",
            "route_name_ar":    "ميكروباص",
            "mode":             "microbus",
            "service_days":     "Ground_Daily",
            "first_arrival":    "07:00:00",
            "last_departure":   "22:00:00",
            "trips": [
              {
                "trip_id":       "...",
                "headsign":      "Asafra",
                "headsign_ar":   "العصافرة",
                "direction_id":  1,
                "service_id":    "Ground_Daily",
              }, ...
            ]
          }
          or None if not found.
        """
        route = _fetch_route_by_gtfs_id(line_id)
        if route is None:
            logger.warning("get_schedule_route_not_found", line_id=line_id)
            return None

        trips     = _fetch_trips_for_route(route.route_id)
        timings   = _fetch_first_last_departure(route.route_id)

        # Collect unique service_ids
        service_ids = list({t.service_id for t in trips if t.service_id})

        result = {
            "route_name":     route.name,
            "route_name_ar":  route.route_short_name_ar,  # from attrs JSONB
            "mode":           route.mode,
            "service_days":   service_ids,
            "first_arrival":  timings["first_arrival"],
            "last_departure": timings["last_departure"],
            "trips": [
                {
                    "trip_id":      str(t.trip_id),
                    "gtfs_trip_id": t.gtfs_trip_id,
                    "headsign":     t.headsign,
                    "headsign_ar":  t.headsign_ar,         # from attrs JSONB
                    "direction_id": t.direction_id,
                    "service_id":   t.service_id,
                }
                for t in trips
            ],
        }

        logger.info(
            "schedule_fetched",
            line_id=line_id,
            route_name=route.name,
            trip_count=len(trips),
        )
        return result

    # Line info 

    def get_line_info(self, line_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch full info about a route.

        Returns:
          {
            "route_id":         internal_id,
            "gtfs_route_id":    "I46ZQc9g0OMvTpnnq0RXs",
            "route_name":       "Asafra - Sidi Bishr",
            "route_name_ar":    "ميكروباص",
            "mode":             "microbus",
            "operator":         "P_O_14",
            "cost_baseline":    5.0,
            "fare_estimate":    FareEstimate,
            "trips": [
              {
                "trip_id":   ...,
                "headsign":  "Asafra",
                "stops": [
                  {
                    "sequence":     1,
                    "stop_name":    "Borg Al-Arab",
                    "stop_name_ar": "...",
                    "arrival":      "07:00:00",
                    "departure":    "07:00:15",
                    "lat":          30.88,
                    "lon":          29.49,
                  }, ...
                ]
              }, ...
            ]
          }
          or None if not found.
        """
        route = _fetch_route_by_gtfs_id(line_id)
        if route is None:
            logger.warning("get_line_info_route_not_found", line_id=line_id)
            return None

        trips      = _fetch_trips_for_route(route.route_id)
        fare_est   = self.get_fare(line_id)

        trips_with_stops = []
        for trip in trips:
            stops = _fetch_stops_for_trip(trip.trip_id)
            trips_with_stops.append({
                "trip_id":      str(trip.trip_id),
                "gtfs_trip_id": trip.gtfs_trip_id,
                "headsign":     trip.headsign,
                "headsign_ar":  trip.headsign_ar,
                "direction_id": trip.direction_id,
                "service_id":   trip.service_id,
                "stops": [
                    {
                        "sequence":     s["stop_sequence"],
                        "stop_name":    s["stop_name"],
                        "stop_name_ar": s["stop_name_ar"],
                        "arrival":      s["arrival_time"],
                        "departure":    s["departure_time"],
                        "lat":          s["lat"],
                        "lon":          s["lon"],
                    }
                    for s in stops
                ],
            })

        result = {
            "route_id":       route.route_id,
            "gtfs_route_id":  route.gtfs_route_id,
            "route_name":     route.name,
            "route_name_ar":  route.route_short_name_ar,
            "mode":           route.mode,
            "operator":       route.operator,
            "cost_baseline":  route.cost,
            "fare_estimate":  fare_est,
            "trips":          trips_with_stops,
        }

        logger.info(
            "line_info_fetched",
            line_id=line_id,
            route_name=route.name,
            trips=len(trips),
        )
        return result

    # Unified dispatcher  

    def query(
        self,
        info_target: str,
        info_params: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Unified query dispatcher for info_request intents.

        Called by agent.py when intent.query_type == INFO_REQUEST.

        Args:
            info_target: "fare" | "schedule" | "line_info"
            info_params: {"line_id": "I46ZQc9g0OMvTpnnq0RXs"} etc.

        Returns:
            Query result dict or None on failure.
        """
        line_id = info_params.get("line_id")

        dispatch = {
            "fare":      self.get_fare,
            "schedule":  self.get_schedule,
            "line_info": self.get_line_info,
        }

        handler = dispatch.get(info_target)
        if handler is None:
            logger.warning("unknown_info_target", target=info_target)
            return None

        if not line_id:
            logger.warning("missing_line_id", target=info_target)
            return None

        result = handler(line_id)

        # FareEstimate needs .dict() for JSON serialization 
        if hasattr(result, "model_dump"):
            return result.model_dump()

        return result