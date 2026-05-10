"""
schema.py 
All Pydantic data models — single source of truth.
"""

from __future__ import annotations 

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator, model_validator

 
# Enums 


class QueryType(str, Enum):
    JOURNEY_REQUEST      = "journey_request"
    FOLLOWUP             = "followup"
    INFO_REQUEST         = "info_request"
    SHOW_MORE            = "show_more"
    SHOW_DETAIL          = "show_detail"
    UNKNOWN              = "unknown"
    CLARIFICATION_NEEDED = "clarification_needed"


class OptimizationGoal(str, Enum):
    MIN_COST       = "min_cost"
    MIN_TIME       = "min_time"
    MIN_TRANSFERS  = "min_transfers"
    MIN_WALKING    = "min_walking"
    BALANCED       = "balanced"
    SAME_AS_BEFORE = "same_as_before"   # for follow-ups
    CUSTOM         = "custom"


class Language(str, Enum):
    ARABIC  = "ar"
    ENGLISH = "en"
    MIXED   = "mixed"


class TransportMode(str, Enum):
    BUS      = "bus"
    METRO    = "metro"
    MICROBUS = "microbus"
    TRAM     = "tram"
    WALK     = "walk"
    UNKNOWN  = "unknown"    # catch-all for unrecognized modes


class RankingSource(str, Enum):
    MNL          = "mnl"
    LTR          = "ltr"
    BLENDED      = "blended"
    MNL_FALLBACK = "mnl_fallback"



# Database Table Schemas
# These match the ACTUAL DB tables (verified against your xlsx imports)


class StopRecord(BaseModel):
    """
    Matches the operational `stop` table.

    Columns:
      stop_id, feed_id, gtfs_stop_id,
      name, geom_4326, geom_22992,
      attrs (JSONB), created_at

    Arabic name → attrs->>'name_ar'

    Coordinates extracted from geom_4326 via:
      ST_Y(geom_4326) AS lat
      ST_X(geom_4326) AS lon

    Used by geo_tool for:
      - pg_trgm fuzzy search on name AND attrs->>'name_ar'
      - PostGIS ST_DWithin nearest-stop query on geom_4326
    """

    #  Core columns 
    stop_id:     Any              # internal PK (int)
    gtfs_stop_id: Optional[str]  = None   # original GTFS stop_id e.g. "189"
    feed_id:     Optional[Any]   = None
    name:        str                       # English name

    #  Coordinates (extracted from geom_4326 by SQL query) 
    # Query: ST_Y(geom_4326) AS lat, ST_X(geom_4326) AS lon
    lat: Optional[float] = None
    lon: Optional[float] = None

    #  JSONB attrs (full dict from DB) 
    attrs: Dict[str, Any] = Field(default_factory=dict)

    #  Derived: Arabic name from attrs 
    @property
    def name_ar(self) -> Optional[str]:
        """Extract Arabic name from attrs JSONB."""
        return self.attrs.get("name_ar")

    @property
    def display_name(self) -> str:
        """Arabic name if available, else English name."""
        return self.name_ar or self.name

    @property
    def coordinate(self) -> Optional["Coordinate"]:
        if self.lat is not None and self.lon is not None:
            return Coordinate(lat=self.lat, lon=self.lon)
        return None

    @property
    def has_coordinates(self) -> bool:
        return self.lat is not None and self.lon is not None


class RouteRecord(BaseModel):
    """
    Matches the operational `route` table.

    Columns:
      route_id, feed_id, gtfs_route_id,
      name, continuous_pickup, continuous_drop_off,
      mode, cost, one_way, operator,
      attrs (JSONB), created_at

    Arabic short name → attrs->>'route_short_name_ar'

    Note: mode is already a text string ("bus", "microbus", etc.)
          No GTFS integer mapping needed for operational table.
          cost is a direct numeric column (EGP baseline).
    """

    #  Core columns 
    route_id:          Any
    feed_id:           Optional[Any]   = None
    gtfs_route_id:     Optional[str]   = None    # original GTFS route_id
    name:              str                        # route display name
    mode:              Optional[str]   = None     # "bus","microbus","metro","tram"
    cost:              Optional[float] = None     # baseline fare EGP
    operator:          Optional[str]   = None     # operating agency
    one_way:           Optional[bool]  = None
    continuous_pickup:   Optional[int] = None
    continuous_drop_off: Optional[int] = None

    #  JSONB attrs 
    attrs: Dict[str, Any] = Field(default_factory=dict)

    #  Derived: Arabic name from attrs 
    @property
    def route_short_name_ar(self) -> Optional[str]:
        """Extract Arabic short name from attrs JSONB."""
        return self.attrs.get("route_short_name_ar")

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def transport_mode(self) -> TransportMode:
        """
        Map route.mode text string to TransportMode enum.
        mode column is already text in operational table.
        """
        if not self.mode:
            return TransportMode.UNKNOWN
        mode_map = {
            "bus":      TransportMode.BUS,
            "microbus": TransportMode.MICROBUS,
            "metro":    TransportMode.METRO,
            "tram":     TransportMode.TRAM,
            "walk":     TransportMode.WALK,
        }
        return mode_map.get(self.mode.lower(), TransportMode.UNKNOWN)


class TripRecord(BaseModel):
    """
    Matches the operational `trip` table.

    Columns:
      trip_id, route_id, feed_id, gtfs_trip_id,
      route_geom_id, headsign, direction_id,
      service_id, attrs (JSONB), created_at

    Arabic headsign → attrs->>'headsign_ar'
    """

    #  Core columns 
    trip_id:       Any
    route_id:      Any
    feed_id:       Optional[Any]  = None
    gtfs_trip_id:  Optional[str]  = None     # original GTFS trip_id
    route_geom_id: Optional[Any]  = None     # FK to route_geometry
    headsign:      Optional[str]  = None     # English headsign e.g. "Asafra"
    direction_id:  Optional[int]  = None     # 0 or 1
    service_id:    Optional[str]  = None     # e.g. "Ground_Daily"

    #  JSONB attrs 
    attrs: Dict[str, Any] = Field(default_factory=dict)

    #  Derived: Arabic headsign from attrs 
    @property
    def headsign_ar(self) -> Optional[str]:
        """Extract Arabic headsign from attrs JSONB."""
        return self.attrs.get("headsign_ar")

    @property
    def display_headsign(self) -> str:
        """Arabic headsign if available, else English."""
        return self.headsign_ar or self.headsign or str(self.trip_id)


class RouteStopRecord(BaseModel):
    """
    Matches the operational `route_stop` table.

    Columns:
      route_stop_id (PK), trip_id, stop_id,
      stop_sequence, arrival_time, departure_time,
      attrs (JSONB), created_at

    Links trips → stops with timing.
    No timepoint column in operational table
    (timepoint exists in gtfs_staging_stop_times only).
    """

    route_stop_id:  Optional[Any]  = None    # PK
    trip_id:        Any
    stop_id:        Any
    stop_sequence:  int
    arrival_time:   Optional[str]  = None    # "HH:MM:SS"
    departure_time: Optional[str]  = None    # "HH:MM:SS"
    attrs:          Dict[str, Any] = Field(default_factory=dict)


class RouteGeometryRecord(BaseModel):
    """
    Matches the operational `route_geometry` table.

    Columns:
      route_geom_id (PK), route_id,
      geom_4326, geom_22992,
      attrs (JSONB), created_at

    geom_4326  → WGS84 (lat/lon) — use for map display
    geom_22992 → Egyptian Transverse Mercator — use for distance calculations
    """

    route_geom_id: Any
    route_id:      Any
    attrs:         Dict[str, Any] = Field(default_factory=dict)
    # Geometry columns not stored as Python fields —
    # extracted in SQL queries using ST_AsGeoJSON(geom_4326)


class FareEstimate(BaseModel):
    """
    Estimated fare from trained fare ML model (model/fare/model.pkl).

    The fare model uses route.cost as a baseline feature plus
    journey characteristics (distance, mode, transfers, time_of_day)
    to predict final fare in EGP.

    Fields:
      route_id       → which route
      baseline_cost  → route.cost from DB (raw baseline)
      estimated_fare → ML model prediction (EGP)
      fare_basis     → "ml_predicted" | "fixed" | "fallback"
      currency       → always "EGP"
      model_version  → tracks model.pkl version
      input_features → features fed to model (for debugging)
    """

    route_id:        Any
    baseline_cost:   Optional[float] = None     # route.cost from DB
    estimated_fare:  float                       # EGP — ML prediction
    fare_basis:      str  = "ml_predicted"       # "ml_predicted"|"fixed"|"fallback"
    currency:        str  = "EGP"
    model_version:   Optional[str]  = None
    input_features:  Dict[str, Any] = Field(default_factory=dict)

    @property
    def display_fare(self) -> str:
        return f"{self.estimated_fare:.1f} {self.currency}"



# Routing Engine API Schemas
# Field names match POST /api/routes EXACTLY



class Coordinate(BaseModel):
    """
    Geographic coordinate.

    Uses `lon` (not `lng`) to be consistent with:
      - DB columns:  stop_lon
      - API fields:  start_lon, end_lon
    """

    lat: float = Field(..., ge=-90.0,  le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)   # lon not lng

    @property
    def as_tuple(self) -> Tuple[float, float]:
        return (self.lat, self.lon)

    def __repr__(self) -> str:
        return f"({self.lat:.6f}, {self.lon:.6f})"


class RoutingWeights(BaseModel):
    """
    Weights passed directly to the routing engine.

    These are SEPARATE from WeightVector (our internal representation).
    Conversion: WeightVector → RoutingWeights happens in routing_tool.py
    """

    weight_time:     float = Field(default=0.25, ge=0.0, le=1.0)
    weight_cost:     float = Field(default=0.25, ge=0.0, le=1.0)
    weight_walk:     float = Field(default=0.25, ge=0.0, le=1.0)
    weight_transfer: float = Field(default=0.25, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def normalize(self) -> "RoutingWeights":
        total = (
            self.weight_time + self.weight_cost
            + self.weight_walk + self.weight_transfer
        )
        if total == 0:
            self.weight_time = self.weight_cost = 0.25
            self.weight_walk = self.weight_transfer = 0.25
        elif abs(total - 1.0) > 0.01:
            self.weight_time     /= total
            self.weight_cost     /= total
            self.weight_walk     /= total
            self.weight_transfer /= total
        return self

    @classmethod
    def from_weight_vector(cls, wv: "WeightVector") -> "RoutingWeights":
        """Convert WeightVector → RoutingWeights (routing engine format)."""
        return cls(
            weight_time=wv.time,
            weight_cost=wv.cost,
            weight_walk=wv.walking,
            weight_transfer=wv.transfers,
        )


class RouteRequest(BaseModel):
    """
    Request body for POST /api/routes.
    Field names and bounds match actual OpenAPI spec EXACTLY.

    Verified bounds:
      max_transfers : [0, 5]
      walking_cutoff: [100, 5000]
      top_k         : [1, 20]
      weight_*      : [0, 1]
    """

    #  Required: coordinates 
    start_lat: float = Field(..., ge=-90.0,  le=90.0)
    start_lon: float = Field(..., ge=-180.0, le=180.0)
    end_lat:   float = Field(..., ge=-90.0,  le=90.0)
    end_lon:   float = Field(..., ge=-180.0, le=180.0)

    #  Optional: routing parameters 
    max_transfers:    int       = Field(default=3,    ge=0,   le=5)
    walking_cutoff:   int       = Field(default=1500, ge=100, le=5000)
    top_k:            int       = Field(default=10,   ge=1,   le=20)
    restricted_modes: List[str] = Field(default_factory=list)

    #  Optional: weights 
    weight_time:     float = Field(default=0.25, ge=0.0, le=1.0)
    weight_cost:     float = Field(default=0.25, ge=0.0, le=1.0)
    weight_walk:     float = Field(default=0.25, ge=0.0, le=1.0)
    weight_transfer: float = Field(default=0.25, ge=0.0, le=1.0)

    @classmethod
    def from_coordinates(
        cls,
        origin:          "Coordinate",
        destination:     "Coordinate",
        weights:         Optional["RoutingWeights"] = None,
        max_transfers:   int = 3,
        walking_cutoff:  int = 1500,
        top_k:           int = 10,
        restricted_modes: Optional[List[str]] = None,
    ) -> "RouteRequest":
        """Factory: build RouteRequest from Coordinate objects."""
        w = weights or RoutingWeights()
        return cls(
            start_lat=origin.lat,
            start_lon=origin.lon,       
            end_lat=destination.lat,
            end_lon=destination.lon,     
            max_transfers=max(0,   min(5,    max_transfers)),
            walking_cutoff=max(100, min(5000, walking_cutoff)),
            top_k=max(1,   min(20,   top_k)),
            restricted_modes=restricted_modes or [],
            weight_time=w.weight_time,
            weight_cost=w.weight_cost,
            weight_walk=w.weight_walk,
            weight_transfer=w.weight_transfer,
        )

    def to_api_dict(self) -> Dict[str, Any]:
        """Serialize to dict for HTTP POST body."""
        d: Dict[str, Any] = {
            "start_lat":       self.start_lat,
            "start_lon":       self.start_lon,
            "end_lat":         self.end_lat,
            "end_lon":         self.end_lon,
            "max_transfers":   self.max_transfers,
            "walking_cutoff":  self.walking_cutoff,
            "top_k":           self.top_k,
            "weight_time":     self.weight_time,
            "weight_cost":     self.weight_cost,
            "weight_walk":     self.weight_walk,
            "weight_transfer": self.weight_transfer,
        }
        if self.restricted_modes:
            d["restricted_modes"] = self.restricted_modes
        return d


class RouteApiResponse(BaseModel):
    """
    Response from POST /api/routes.

    IMPORTANT: The API declares response as "string".
    We parse carefully — handles all possible formats.
    """

    raw: Any

    @classmethod
    def parse_response(cls, raw_response: Any) -> List[Dict[str, Any]]:
        """Safely extract list of journey dicts from API response."""
        if isinstance(raw_response, str):
            try:
                parsed = json.loads(raw_response)
                return cls._extract_list(parsed)
            except json.JSONDecodeError:
                return []
        return cls._extract_list(raw_response)

    @staticmethod
    def _extract_list(data: Any) -> List[Dict[str, Any]]:
        """Extract list of journey dicts from any structure."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("routes", "journeys", "results", "data"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []



# Intent JSON — Output of fine-tuned model



class WeightVector(BaseModel):
    """
    Internal optimization weights — auto-normalized to sum to 1.0.

    Naming mapping to routing engine:
      WeightVector.time      ↔ RoutingWeights.weight_time
      WeightVector.cost      ↔ RoutingWeights.weight_cost
      WeightVector.walking   ↔ RoutingWeights.weight_walk
      WeightVector.transfers ↔ RoutingWeights.weight_transfer
    """

    cost:      float = Field(default=0.25, ge=0.0, le=1.0)
    time:      float = Field(default=0.25, ge=0.0, le=1.0)
    transfers: float = Field(default=0.25, ge=0.0, le=1.0)
    walking:   float = Field(default=0.25, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def normalize_weights(self) -> "WeightVector":
        total = self.cost + self.time + self.transfers + self.walking
        if total == 0:
            self.cost = self.time = self.transfers = self.walking = 0.25
        elif abs(total - 1.0) > 0.01:
            self.cost      /= total
            self.time      /= total
            self.transfers /= total
            self.walking   /= total
        return self

    @classmethod
    def from_optimization(cls, goal: OptimizationGoal) -> "WeightVector":
        presets = {
            OptimizationGoal.MIN_COST: cls(
                cost=0.90, time=0.05, transfers=0.03, walking=0.02
            ),
            OptimizationGoal.MIN_TIME: cls(
                cost=0.05, time=0.90, transfers=0.03, walking=0.02
            ),
            OptimizationGoal.MIN_TRANSFERS: cls(
                cost=0.05, time=0.10, transfers=0.80, walking=0.05
            ),
            OptimizationGoal.MIN_WALKING: cls(
                cost=0.05, time=0.10, transfers=0.10, walking=0.75
            ),
            OptimizationGoal.BALANCED: cls(
                cost=0.25, time=0.25, transfers=0.25, walking=0.25
            ),
        }
        return presets.get(goal, cls())

    def to_routing_weights(self) -> "RoutingWeights":
        """Convert to routing engine weight format."""
        return RoutingWeights.from_weight_vector(self)


class Constraint(BaseModel):
    """Hard constraint a journey must satisfy."""

    field:    str    # "fare", "duration", "transfers", "walking"
    operator: str    # "lte", "gte", "eq", "lt", "gt"
    value:    float

    def evaluate(self, journey: "Journey") -> bool:
        field_map = {
            "fare":      "total_fare_egp",
            "duration":  "total_duration_minutes",
            "transfers": "transfers",
            "walking":   "total_walking_meters",
        }
        journey_field = field_map.get(self.field, self.field)
        journey_val = getattr(journey, journey_field, None)
        if journey_val is None:
            return True
        ops = {
            "lte": lambda a, b: a <= b,
            "gte": lambda a, b: a >= b,
            "eq":  lambda a, b: abs(a - b) < 0.01,
            "lt":  lambda a, b: a < b,
            "gt":  lambda a, b: a > b,
        }
        fn = ops.get(self.operator)
        return fn(journey_val, self.value) if fn else True


class Intent(BaseModel):
    """Structured intent extracted from user text."""

    query_type:   QueryType        = QueryType.UNKNOWN
    origin:       Optional[str]    = None
    destination:  Optional[str]    = None
    optimization: OptimizationGoal = OptimizationGoal.BALANCED
    weights:      WeightVector     = Field(default_factory=WeightVector)
    constraints:  List[Constraint] = Field(default_factory=list)
    also_report:  List[str]        = Field(default_factory=list)
    language:     Language         = Language.ARABIC
    confidence:   float            = Field(default=1.0, ge=0.0, le=1.0)
    raw_text:     Optional[str]    = None
    result_index: Optional[int]    = None
    info_target:  Optional[str]    = None
    info_params:  Dict[str, Any]   = Field(default_factory=dict)

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def clean_location(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = str(v).strip()
        return v if v else None

    @model_validator(mode="after")
    def sync_weights_with_optimization(self) -> "Intent":
        skip = {
            OptimizationGoal.BALANCED,
            OptimizationGoal.SAME_AS_BEFORE,
            OptimizationGoal.CUSTOM,
        }
        if self.optimization not in skip:
            w = self.weights
            if abs(w.cost - 0.25) < 0.01 and abs(w.time - 0.25) < 0.01:
                self.weights = WeightVector.from_optimization(self.optimization)
        return self

    @property
    def missing_fields(self) -> List[str]:
        missing = []
        if self.query_type == QueryType.JOURNEY_REQUEST:
            if not self.origin:
                missing.append("origin")
            if not self.destination:
                missing.append("destination")
        return missing

    @property
    def is_complete(self) -> bool:
        return len(self.missing_fields) == 0



# Journey — Internal representation



class Step(BaseModel):
    """
    One step in a multi-modal journey.

    Added Arabic name fields for bilingual response building.
    """

    mode:               TransportMode
    line_id:            Optional[str]  = None
    line_name:          Optional[str]  = None
    line_name_ar:       Optional[str]  = None    # Arabic line name
    headsign:           Optional[str]  = None    # trip headsign
    headsign_ar:        Optional[str]  = None    # Arabic headsign

    from_stop_id:       Optional[str]  = None
    from_stop_name:     str            = ""
    from_stop_name_ar:  Optional[str]  = None    # Arabic stop name

    to_stop_id:         Optional[str]  = None
    to_stop_name:       str            = ""
    to_stop_name_ar:    Optional[str]  = None    # Arabic stop name

    duration_minutes:   float          = 0.0
    distance_meters:    float          = 0.0
    fare_egp:           float          = 0.0
    departure_time:     Optional[str]  = None
    arrival_time:       Optional[str]  = None


class Journey(BaseModel):
    """
    Internal journey representation.
    Parsed from routing engine response, enriched by ranking layer.
    """

    #  Identity 
    journey_id: str

    #  Coordinates 
    origin_lat:      float
    origin_lon:      float          # was origin_lng, now origin_lon
    destination_lat: float
    destination_lon: float          # was destination_lng, now destination_lon

    #  Steps 
    steps: List[Step] = Field(default_factory=list)

    #  Totals 
    total_duration_minutes: float
    total_fare_egp:         float
    transfers:              int
    total_walking_meters:   float         = 0.0
    departure_time:         Optional[str] = None
    arrival_time:           Optional[str] = None

    #  Ranking enrichment 
    score:              float            = 0.0
    rank:               int              = 0
    ranking_source:     RankingSource    = RankingSource.MNL
    rank_reason:        str              = ""
    feature_importance: Dict[str, float] = Field(default_factory=dict)

    #  Convenience properties 
    @property
    def fare(self) -> float:
        return self.total_fare_egp

    @property
    def duration(self) -> float:
        return self.total_duration_minutes

    @property
    def walking(self) -> float:
        return self.total_walking_meters

    def satisfies_constraints(self, constraints: List[Constraint]) -> bool:
        return all(c.evaluate(self) for c in constraints)

    def to_feature_vector(self, time_of_day: Optional[int] = None) -> List[float]:
        hour = time_of_day if time_of_day is not None else datetime.now().hour
        return [
            self.total_duration_minutes,
            self.total_fare_egp,
            float(self.transfers),
            float(len(self.steps)),
            self.total_walking_meters,
            float(hour),
            float(7 <= hour <= 9),    # morning peak
            float(17 <= hour <= 19),  # evening peak
        ]



# Conversation Memory Schemas



@dataclass
class ConversationTurn:
    turn_id:            int
    user_input:         str
    intent:             Intent
    all_journeys:       List[Journey] = field(default_factory=list)
    ranked_journeys:    List[Journey] = field(default_factory=list)
    displayed_journeys: List[Journey] = field(default_factory=list)
    response_text:      str           = ""
    timestamp:          datetime      = field(default_factory=datetime.now)
    was_followup:       bool          = False
    was_clarification:  bool          = False


@dataclass
class MemoryContext:
    has_active_journeys:  bool
    all_journeys:         List[Journey]
    ranked_journeys:      List[Journey]
    displayed_journeys:   List[Journey]
    display_cursor:       int
    last_origin:          Optional[str]
    last_destination:     Optional[str]
    # Coordinates — uses lon (consistent with DB + API)
    last_origin_lat:      Optional[float]
    last_origin_lon:      Optional[float]      # was last_origin_lng
    last_destination_lat: Optional[float]
    last_destination_lon: Optional[float]      # was last_destination_lng
    last_optimization:    Optional[OptimizationGoal]
    last_weights:         Optional[WeightVector]
    turn_count:           int
    last_intent:          Optional[Intent]



# API Request / Response



class AgentResponse(BaseModel):
    text:      str
    language:  Language
    journeys:  List[Journey]    = Field(default_factory=list)
    intent:    Optional[Intent] = None
    turn_id:   int              = 0
    has_more:  bool             = False
    error:     Optional[str]    = None
    debug:     Dict[str, Any]   = Field(default_factory=dict)


class ChatRequest(BaseModel):
    message:       str               = Field(..., min_length=1, max_length=1000)
    session_id:    str               = Field(..., min_length=1, max_length=100)
    language_hint: Optional[Language] = None

    @field_validator("message")
    @classmethod
    def clean_message(cls, v: str) -> str:
        v = v.strip()
        v = re.sub(r"\s+", " ", v)
        return v