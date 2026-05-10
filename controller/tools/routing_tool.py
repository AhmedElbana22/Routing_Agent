"""
routing_tool.py
HTTP client for the Routing Engine API.

API: POST https://routing-demo-eval.azurewebsites.net/api/routes
     GET  .../api/health

Takes:  Coordinate objects (lat/lon) + WeightVector
        -> builds RouteRequest → POSTs to API
        -> parses response → returns List[Journey]

Key facts:
  - API takes COORDINATES (lat/lon), NOT stop IDs
  - HTTP method is POST with JSON body (not GET with query params)
  - Endpoint is /api/routes (not /journeys)
  - Weights (time/cost/walk/transfer) are passed in the POST body
  - Response may be a JSON string (needs double-parsing)
  - Uses RouteRequest + RouteApiResponse from schema.py
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from config import settings
from model.intent.schema import (
    Coordinate,
    Journey,
    RouteApiResponse,
    RouteRequest,
    RoutingWeights,
    Step,
    TransportMode,
    WeightVector,
)
import structlog

logger = structlog.get_logger(__name__)

 

# Transport mode mapper 


# Maps routing API mode strings -> TransportMode enum
# API may return many variants — all mapped safely
_MODE_MAP: dict = {
    # Standard
    "bus":       TransportMode.BUS,
    "microbus":  TransportMode.MICROBUS,
    "metro":     TransportMode.METRO,
    "tram":      TransportMode.TRAM,
    "walk":      TransportMode.WALK,
    # Common API variants
    "walking":   TransportMode.WALK,
    "foot":      TransportMode.WALK,
    "transit":   TransportMode.BUS,
    "rail":      TransportMode.METRO,
    "subway":    TransportMode.METRO,
    "minibus":   TransportMode.MICROBUS,
    "mini_bus":  TransportMode.MICROBUS,
}


def _parse_mode(raw_mode: Optional[str]) -> TransportMode:
    """
    Safely parse mode string → TransportMode.
    Never crashes — returns UNKNOWN for unrecognized modes.
    """
    if not raw_mode:
        return TransportMode.UNKNOWN
    return _MODE_MAP.get(raw_mode.lower().strip(), TransportMode.UNKNOWN)

 

# Response parsers 


def _parse_step(raw: dict) -> Step:
    """Parse a single leg from routing engine response."""
    leg_type = raw.get("type", "")  # "walk" or "trip"
    
    if leg_type == "walk":
        return Step(
            mode=TransportMode.WALK,
            duration_minutes=float(raw.get("duration_minutes") or 0.0),
            distance_meters=float(raw.get("distance_meters") or 0.0),
            fare_egp=0.0,
        )
    else:  # "trip"
        from_stop = raw.get("from", {})
        to_stop   = raw.get("to",   {})
        return Step(
            mode=_parse_mode(raw.get("mode")),
            line_id=raw.get("trip_id"),
            line_name=raw.get("route_short_name"),
            headsign=raw.get("headsign"),
            from_stop_id=str(from_stop.get("stop_id")) if from_stop.get("stop_id") else None,
            from_stop_name=from_stop.get("name", ""),
            to_stop_id=str(to_stop.get("stop_id")) if to_stop.get("stop_id") else None,
            to_stop_name=to_stop.get("name", ""),
            duration_minutes=float(raw.get("duration_minutes") or 0.0),
            distance_meters=float(raw.get("distance_meters")  or 0.0),
            fare_egp=float(raw.get("fare") or 0.0),  # ← "fare" not "fare_egp"
            departure_time=raw.get("departure_time"),
            arrival_time=raw.get("arrival_time"),
        )


def _parse_journey(raw: dict, origin: Coordinate, dest: Coordinate) -> Journey:
    """Parse a journey from routing engine response."""
    
    # API uses "legs" not "steps" 
    steps = []
    for leg in raw.get("legs", []):
        try:
            steps.append(_parse_step(leg))
        except Exception as e:
            logger.warning("step_parse_error", error=str(e))

    # API totals are in "summary" dict 
    summary = raw.get("summary", {})
    
    total_duration = float(summary.get("total_time_minutes") or 
                          sum(s.duration_minutes for s in steps))
    total_fare     = float(summary.get("cost") or 
                          sum(s.fare_egp for s in steps))
    transfers      = int(summary.get("transfers", 0))
    total_walking  = float(summary.get("walking_distance_meters") or
                          sum(s.distance_meters for s in steps 
                              if s.mode == TransportMode.WALK))

    return Journey(
        journey_id=str(raw.get("id") or str(uuid.uuid4())),
        origin_lat=origin.lat,
        origin_lon=origin.lon,
        destination_lat=dest.lat,
        destination_lon=dest.lon,
        steps=steps,
        total_duration_minutes=total_duration,
        total_fare_egp=total_fare,
        transfers=transfers,
        total_walking_meters=total_walking,
        departure_time=raw.get("departure_time"),
        arrival_time=raw.get("arrival_time"),
    )


 
# RoutingTool
 

class RoutingTool:
    """
    HTTP client for the Routing Engine API.

    Takes Coordinate objects + WeightVector → returns List[Journey].

    Flow:
      1. Build RouteRequest from coordinates + weights
      2. POST to /api/routes with JSON body
      3. Parse response via RouteApiResponse (handles string response)
      4. Convert raw dicts → Journey objects
      5. Return list, never raises
    """

    def __init__(self): 
        self._routes_url = settings.routing.routes_url    
        self._health_url = settings.routing.health_url
        self._timeout    = settings.routing.timeout
 

    # Internal API call — with retry 

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(settings.routing.max_retries),
        wait=wait_exponential(
            multiplier=1,
            min=settings.routing.retry_wait_seconds,
            max=8,
        ),
        reraise=True,
    )
    def _call_api(self, request: RouteRequest) -> List[dict]:
        """
        POST to /api/routes with JSON body.
        Returns list of raw journey dicts.

        Uses RouteRequest.to_api_dict() for serialization.
        Uses RouteApiResponse.parse_response() for flexible parsing.

        Note: API response may be a JSON-encoded string
              (RouteApiResponse handles this).
        """
        body = request.to_api_dict()

        logger.info(
            "routing_api_call",
            url=self._routes_url,
            start_lat=body["start_lat"],
            start_lon=body["start_lon"],
            end_lat=body["end_lat"],
            end_lon=body["end_lon"],
            top_k=body["top_k"],
            weight_time=body["weight_time"],
            weight_cost=body["weight_cost"],
        )

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(          
                self._routes_url,
                json=body,                   
            )
            response.raise_for_status()
            raw_response = response.json()

        # Parse response flexibly (may be string, list, or dict) 
        journeys = RouteApiResponse.parse_response(raw_response)

        logger.debug(
            "routing_api_raw_response",
            response_type=type(raw_response).__name__,
            journeys_found=len(journeys),
        )

        return journeys
 

    # Public interface 

    def get_journeys(
        self,
        origin:      Coordinate,
        destination: Coordinate,
        weights:     Optional[WeightVector] = None,
        top_k:       Optional[int]          = None,
        max_transfers: Optional[int]        = None,
        walking_cutoff: Optional[int]       = None,
    ) -> List[Journey]:
        """
        Get journeys from routing engine.
        Returns empty list on any failure — never raises.

        Args:
            origin:         Origin Coordinate(lat, lon) from geo_tool
            destination:    Destination Coordinate(lat, lon) from geo_tool
            weights:        WeightVector from intent (time/cost/walk/transfers)
                            → converted to RoutingWeights for API
            top_k:          Max journeys to request (default: settings.routing.top_k)
            max_transfers:  Max transfers allowed (default: settings.routing.max_transfers)
            walking_cutoff: Max walking meters (default: settings.routing.walking_cutoff)

        Returns:
            List[Journey] sorted by API score (already ranked by engine)

        Usage in agent.py:
            origin_coord, dest_coord = geo_tool.resolve_pair_to_coordinates(...)
            journeys = routing_tool.get_journeys(
                origin=origin_coord,
                destination=dest_coord,
                weights=intent.weights,
            )
        """
        # Guard: same location  
        if (
            abs(origin.lat - destination.lat) < 1e-6
            and abs(origin.lon - destination.lon) < 1e-6
        ):
            logger.warning(
                "same_origin_destination",
                lat=origin.lat,
                lon=origin.lon,
            )
            return []

        # Build RouteRequest  => convert WeightVector → RoutingWeights, apply defaults/clamping
        routing_weights = (
            weights.to_routing_weights()
            if weights is not None
            else RoutingWeights()
        )

        # Clamp to valid API ranges via settings helper
        clamped = settings.routing.clamp_params(
            max_transfers=max_transfers  or settings.routing.max_transfers,
            walking_cutoff=walking_cutoff or settings.routing.walking_cutoff,
            top_k=top_k                  or settings.routing.top_k,
        )

        request = RouteRequest.from_coordinates(
            origin=origin,
            destination=destination,
            weights=routing_weights,
            **clamped,
        )

        # Call API  
        try:
            raw_journeys = self._call_api(request)

            journeys: List[Journey] = []
            for raw in raw_journeys:
                try:
                    journey = _parse_journey(raw, origin, destination)
                    journeys.append(journey)
                except Exception as e:
                    logger.warning(
                        "journey_parse_error",
                        error=str(e),
                        raw_keys=list(raw.keys()) if isinstance(raw, dict) else "not_dict",
                    )

            logger.info(
                "journeys_fetched",
                origin_lat=origin.lat,
                origin_lon=origin.lon,
                dest_lat=destination.lat,
                dest_lon=destination.lon,
                requested=clamped["top_k"],
                returned=len(journeys),
            )
            return journeys

        except httpx.TimeoutException:
            logger.error(
                "routing_api_timeout",
                url=self._routes_url,
                timeout=self._timeout,
            )
            return []

        except httpx.HTTPStatusError as e:
            logger.error(
                "routing_api_http_error",
                status_code=e.response.status_code,
                url=self._routes_url,
                body=e.response.text[:200],
            )
            return []

        except Exception as e:
            logger.error(
                "routing_api_unexpected_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            return []
 

    # Health check 

    def health_check(self) -> bool:
        """
        Check if routing engine is reachable.
        Returns True if healthy, False otherwise.

        Used by main.py startup check.
        """
        try:
            with httpx.Client(timeout=5) as client:
                response = client.get(self._health_url)
                is_healthy = response.status_code == 200
                logger.info(
                    "routing_health_check",
                    healthy=is_healthy,
                    status_code=response.status_code,
                )
                return is_healthy
        except Exception as e:
            logger.warning("routing_health_check_failed", error=str(e))
            return False