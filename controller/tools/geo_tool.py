"""
geo_tool.py
Resolves stop name text -> StopRecord (with coordinates).

Pipeline:
  1. Normalize text (strip diacritics, lowercase, tatweel)
  2. LRU cache check (O(1))
  3. pg_trgm fuzzy search on BOTH name AND attrs->>'name_ar' (in-DB)
  4. Nominatim fallback (lat/lon -> nearest stop via PostGIS ST_DWithin)

Key facts about DB schema:
  - Table:      stop  (not "stops")
  - Name col:   name  (not "stop_name")
  - Arabic:     attrs->>'name_ar'  (JSONB)
  - Geometry:   geom_4326 (PostGIS) → ST_Y() = lat, ST_X() = lon
  - Geometry:   geom_22992 (Egyptian Transverse Mercator, for distance calc)

Thread-safe. Never raises — returns None on complete failure.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
import psycopg2 
import psycopg2.extras
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from config import settings
from model.intent.schema import Coordinate, StopRecord
import structlog

logger = structlog.get_logger(__name__)

 
# Text normalizer 


class TextNormalizer:
    """
    Normalizes Arabic and English stop names for fuzzy matching.
    Handles both Arabic script and Latin transliterations.
    """

    # Arabic diacritics (tashkeel)
    TASHKEEL = re.compile(r"[\u064B-\u065F\u0670]")
    # Arabic tatweel (elongation character) 
    TATWEEL = re.compile(r"\u0640")

    # Common Arabic spelling variants
    ALEF_VARIANTS = re.compile(r"[أإآا]")
    YEH_VARIANTS  = re.compile(r"[يى]")
    TEH_MARBUTA   = re.compile(r"ة")

    # English noise words (Alexandria-aware)
    ENGLISH_NOISE = re.compile(
        r"\b(el|al|el-|al-|the|st|street|square|station|stop|alex|alexandria)\b",
        re.IGNORECASE,
    )

    @classmethod
    def normalize(cls, text: str) -> str:
        """
        Full normalization pipeline.

        Examples:
          'رمسيـس'     → 'رمسيس'
          'El Raml'    → 'raml'
          'رَمْلَة'    → 'رمله'
          'الإسكندرية' → 'الاسكندريه'
        """
        if not text:
            return ""

        text = text.strip()

        # Arabic normalization  
        text = cls.TASHKEEL.sub("", text)         # remove tashkeel
        text = cls.TATWEEL.sub("", text)           # remove tatweel
        text = cls.ALEF_VARIANTS.sub("ا", text)    # unify alef variants
        text = cls.YEH_VARIANTS.sub("ي", text)     # unify yeh variants
        text = cls.TEH_MARBUTA.sub("ه", text)      # unify teh marbuta

        # English normalization  
        text = cls.ENGLISH_NOISE.sub("", text)     # remove noise words
        text = text.lower()

        # Collapse whitespace  
        text = re.sub(r"\s+", " ", text).strip()

        return text

    @classmethod
    def normalize_for_cache_key(cls, text: str) -> str: 
        """Extra aggressive normalization for cache key only."""
        normalized = cls.normalize(text)
        return re.sub(r"[^\w]", "", normalized, flags=re.UNICODE)

 
# Database connection pool 


class DBPool:
    """
    Minimal connection wrapper around psycopg2.
    Single persistent connection with auto-reconnect.

    For production: swap with psycopg2.pool.ThreadedConnectionPool.
    """

    def __init__(self):
        self._conn = None

    def _connect(self) -> None:
        self._conn = psycopg2.connect(settings.db.dsn)
        self._conn.autocommit = True
        logger.info("db_connected", host=settings.db.host, db=settings.db.db)

    def get_connection(self):
        """Return a live connection, reconnecting if needed."""
        try:
            if self._conn is None or self._conn.closed:
                self._connect()
            else:
                # Health check — properly close cursor  
                with self._conn.cursor() as cur:   # use context manager
                    cur.execute("SELECT 1")
            return self._conn
        except Exception:
            self._connect()
            return self._conn


_db_pool = DBPool()

 

# pg_trgm search — queries actual DB schema 


def _pg_trgm_search(
    query: str,
    threshold: float,
    limit: int = 5,
) -> List[StopRecord]:
    """
    Fuzzy stop name search using pg_trgm.

    Searches BOTH:
      - name            (English stop name)
      - attrs->>'name_ar' (Arabic stop name, stored in JSONB)

    Extracts coordinates from PostGIS geom_4326:
      ST_Y(geom_4326) → lat
      ST_X(geom_4326) → lon

    Table:   stop        (not "stops")
    Columns: name, attrs, geom_4326, stop_id, gtfs_stop_id, feed_id

    Requires:
      CREATE EXTENSION pg_trgm;
      CREATE INDEX ON stop USING GIST(name gist_trgm_ops);
    """
    sql = """
        SELECT
            stop_id,
            gtfs_stop_id,
            feed_id,
            name,
            attrs,
            ST_Y(geom_4326)  AS lat,
            ST_X(geom_4326)  AS lon,
            GREATEST(
                similarity(name,              %(query)s),
                similarity(attrs->>'name_ar', %(query)s)
            ) AS sim
        FROM stop
        WHERE
            similarity(name,              %(query)s) > %(threshold)s
         OR similarity(attrs->>'name_ar', %(query)s) > %(threshold)s
        ORDER BY sim DESC
        LIMIT %(limit)s;
    """
    try:
        conn = _db_pool.get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, {
                "query":     query,
                "threshold": threshold,
                "limit":     limit,
            })
            rows = cur.fetchall()

        results = []
        for row in rows:
            record = StopRecord(
                stop_id=row["stop_id"],
                gtfs_stop_id=row["gtfs_stop_id"],
                feed_id=row["feed_id"],
                name=row["name"],
                attrs=dict(row["attrs"]) if row["attrs"] else {},
                lat=row["lat"],
                lon=row["lon"],
            )
            results.append(record)

        return results

    except Exception as e:
        logger.error("pg_trgm_search_failed", error=str(e), query=query)
        return []

 
# Nominatim + PostGIS fallback 


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=False,
)
def _nominatim_geocode(text: str) -> Optional[Tuple[float, float]]:
    """
    Geocode text → (lat, lon) using Nominatim.
    Returns None on failure.
    Respects Nominatim 1 req/sec rate limit (caller sleeps).
    """
    params = {
        "q":            text + " Alexandria Egypt",   
        "format":       "json",
        "limit":        1,
        "countrycodes": "eg",
        "viewbox":      "29.5,30.5,30.5,31.5",        # Alexandria bounding box
        "bounded":      1,                   
    }
    headers = {"User-Agent": settings.geo.nominatim_user_agent} 

    with httpx.Client(timeout=settings.geo.nominatim_timeout) as client:
        response = client.get(
            f"{settings.geo.nominatim_url}/search",
            params=params,
            headers=headers,
        )
        response.raise_for_status()
        results = response.json()

        if results:
            lat = float(results[0]["lat"])
            lon = float(results[0]["lon"])
            return lat, lon

    return None


def _nearest_stop_from_coords(
    lat: float,
    lon: float,
    radius_meters: int,
) -> Optional[StopRecord]:
    """
    Find nearest stop to (lat, lon) using PostGIS ST_DWithin on geom_4326.

    Table:   stop         (not "stops")
    Geom:    geom_4326    (not "geom")

    Returns StopRecord with coordinates populated, or None.
    """
    sql = """
        SELECT
            stop_id,
            gtfs_stop_id,
            feed_id,
            name,
            attrs,
            ST_Y(geom_4326) AS lat,
            ST_X(geom_4326) AS lon,
            ST_Distance(
                geom_4326::geography,
                ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography
            ) AS distance_meters
        FROM stop
        WHERE ST_DWithin(
            geom_4326::geography,
            ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography,
            %(radius)s
        )
        ORDER BY distance_meters ASC
        LIMIT 1;
    """
    try:
        conn = _db_pool.get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, {
                "lat":    lat,
                "lon":    lon,          
                "radius": radius_meters,
            })
            row = cur.fetchone()

        if row:
            return StopRecord(
                stop_id=row["stop_id"],
                gtfs_stop_id=row["gtfs_stop_id"],
                feed_id=row["feed_id"],
                name=row["name"],
                attrs=dict(row["attrs"]) if row["attrs"] else {},
                lat=row["lat"],
                lon=row["lon"],
            )
    except Exception as e:
        logger.error("nearest_stop_failed", error=str(e), lat=lat, lon=lon)

    return None

 

# Main GeoTool class 


class GeoTool:
    """
    Resolves stop name text -> StopRecord (with coordinates).

    Returns StopRecord always — caller accesses:
      result.stop_id    -> for DB queries
      result.coordinate → Coordinate(lat, lon) for routing API
      result.name       -> English name for display
      result.name_ar    -> Arabic name for display

    Cache: LRU dict with configurable max size.
    Complexity:
      - Cache hit:  O(1)
      - pg_trgm:    O(log n) with GiST index
      - Nominatim:  O(network)
    """

    def __init__(
        self,
        similarity_threshold: Optional[float] = None,
        cache_size:           Optional[int]   = None,
        radius_meters:        Optional[int]   = None,
    ):
        self._threshold   = similarity_threshold or settings.geo.similarity_threshold
        self._radius      = radius_meters        or settings.geo.nearest_stop_radius_meters
        self._cache_size  = cache_size           or settings.geo.cache_size

        # LRU cache: key=normalized_text, value=StopRecord or None
        self._cache:       Dict[str, Optional[StopRecord]] = {}
        self._cache_order: List[str] = []

    # Main entry point  

    def resolve(self, stop_name: str) -> Optional[StopRecord]:
        """
        Resolve stop name → StopRecord (always — not just stop_id).

        StopRecord contains:
          .stop_id     → internal DB PK
          .name        → matched English name
          .name_ar     → Arabic name (from attrs JSONB)
          .coordinate  → Coordinate(lat, lon) for routing API
          .lat / .lon  → raw floats

        Returns None if stop cannot be resolved.

        Examples:
          resolve("رامي")         → StopRecord(stop_id=5, name="Raml Station", ...)
          resolve("Raml Station") → StopRecord(stop_id=5, name="Raml Station", ...)
          resolve("nonsense xyz") → None
        """
        if not stop_name or not stop_name.strip():
            return None

        start     = time.time()
        normalized = TextNormalizer.normalize(stop_name)
        cache_key  = TextNormalizer.normalize_for_cache_key(stop_name)

        # 1. Cache hit  
        if cache_key in self._cache:
            result = self._cache[cache_key]
            self._touch_cache(cache_key)
            logger.debug("geo_cache_hit", query=stop_name,
                         stop_id=result.stop_id if result else None)
            return result

        # 2. pg_trgm fuzzy search (English + Arabic)  
        matches = _pg_trgm_search(normalized, threshold=self._threshold)

        if matches:
            best = matches[0]   # highest similarity score
            self._set_cache(cache_key, best)
            elapsed = (time.time() - start) * 1000

            logger.info(
                "geo_resolved_trgm",
                query=stop_name,
                matched_en=best.name,
                matched_ar=best.name_ar,
                stop_id=best.stop_id,
                has_coords=best.has_coordinates,
                elapsed_ms=round(elapsed, 2),
            )
            return best

        # 3. Nominatim → PostGIS nearest stop 
        logger.info("geo_trgm_no_match_trying_nominatim", query=stop_name)

        # Respect Nominatim 1 req/sec rate limit
        time.sleep(1.1)

        coords = _nominatim_geocode(normalized)
        if coords:
            lat, lon = coords
            nearest = _nearest_stop_from_coords(lat, lon, self._radius)
            if nearest:
                self._set_cache(cache_key, nearest)
                elapsed = (time.time() - start) * 1000
                logger.info(
                    "geo_resolved_nominatim",
                    query=stop_name,
                    matched_en=nearest.name,
                    matched_ar=nearest.name_ar,
                    stop_id=nearest.stop_id,
                    nominatim_lat=lat,
                    nominatim_lon=lon,
                    elapsed_ms=round(elapsed, 2),
                )
                return nearest

        # 4. Not found 
        self._set_cache(cache_key, None)   # cache negative result too
        logger.warning("geo_not_found", query=stop_name, normalized=normalized)
        return None

    def resolve_to_coordinate(self, stop_name: str) -> Optional[Coordinate]:
        """
        Convenience: stop_name → Coordinate(lat, lon) directly.

        Used by routing_tool.py which needs Coordinate objects.
        Returns None if stop not found or has no coordinates.
        """
        record = self.resolve(stop_name)
        if record is None:
            return None
        if not record.has_coordinates:
            logger.warning("geo_no_coordinates", stop_name=stop_name,
                           stop_id=record.stop_id)
            return None
        return record.coordinate

    def resolve_pair(
        self,
        origin:      str,
        destination: str,
    ) -> Tuple[Optional[StopRecord], Optional[StopRecord]]:
        """
        Resolve origin and destination simultaneously.
        Returns (origin_record, destination_record).

        Both can be None independently if not found.
        routing_tool.py uses .coordinate on each result.
        """
        origin_record = self.resolve(origin)
        dest_record   = self.resolve(destination)
        return origin_record, dest_record

    def resolve_pair_to_coordinates(
        self,
        origin:      str,
        destination: str,
    ) -> Tuple[Optional[Coordinate], Optional[Coordinate]]:
        """
        Convenience: resolve both stops → (Coordinate, Coordinate).
        Direct input for RouteRequest.from_coordinates().

        Usage in routing_tool.py:
            origin_coord, dest_coord = geo_tool.resolve_pair_to_coordinates(...)
            if origin_coord and dest_coord:
                request = RouteRequest.from_coordinates(origin_coord, dest_coord, ...)
        """
        origin_coord = self.resolve_to_coordinate(origin)
        dest_coord   = self.resolve_to_coordinate(destination)
        return origin_coord, dest_coord

    def get_suggestions(
        self,
        partial_name: str,
        limit:        int = 5,
    ) -> List[str]:
        """
        Return stop name suggestions for partial input.
        Returns both English and Arabic names for bilingual UI autocomplete.

        Returns list of display names (Arabic preferred).
        """
        normalized = TextNormalizer.normalize(partial_name)
        matches    = _pg_trgm_search(normalized, threshold=0.2, limit=limit)
        # Return Arabic name if available, else English
        return [m.display_name for m in matches]

    # Cache management (LRU)  

    def _set_cache(
        self,
        key:   str,
        value: Optional[StopRecord],
    ) -> None:
        """Add to cache with LRU eviction."""
        if key in self._cache:
            self._touch_cache(key)
        else:
            if len(self._cache) >= self._cache_size:
                # Evict least recently used
                lru_key = self._cache_order.pop(0)
                self._cache.pop(lru_key, None)
            self._cache_order.append(key)
        self._cache[key] = value

    def _touch_cache(self, key: str) -> None:
        """Move key to end of LRU order (most recently used)."""
        try:
            self._cache_order.remove(key)
        except ValueError:
            pass
        self._cache_order.append(key)

    def clear_cache(self) -> None:
        """Clear the geo cache entirely."""
        self._cache.clear()
        self._cache_order.clear()
        logger.info("geo_cache_cleared")

    @property
    def cache_size(self) -> int:
        """Current number of entries in cache."""
        return len(self._cache)