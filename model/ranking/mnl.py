"""
mnl.py
Multinomial Logit (MNL) baseline ranker.

U(j) = w_cost*(1-fare_norm) + w_time*(1-duration_norm)
     + w_transfers*(1-transfer_norm) + w_walking*(1-walking_norm)

Interpretable, no training needed, always available.
O(n) scoring, O(n log n) for sort.

Normalization stats tuned for Alexandria microbus network:
  fare:      max ~30 EGP   (short urban trips)
  duration:  max ~90 min   (cross-city Alexandria)
  transfers: max 3
  walking:   max 1500m
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from model.intent.schema import Journey, WeightVector
import structlog

logger = structlog.get_logger(__name__)


#  Normalization stats for Alexandria network 
# Update these based on actual journey data once collected
ALEX_NORM_STATS = {
    "fare_max":      30.0,    # EGP — Alexandria microbus fares are lower than Cairo
    "duration_max":  90.0,    # minutes — shorter cross-city distances
    "transfers_max": 3.0,     # realistic max transfers in Alexandria
    "walking_max":   1500.0,  # meters — matches GEO_NEAREST_STOP_RADIUS
}


def _normalize(value: float, max_val: float) -> float:
    """Normalize value to [0, 1]. Clips outliers at max_val."""
    if max_val <= 0:
        return 0.0
    return min(value / max_val, 1.0)


class MNLScorer:
    """
    Multinomial Logit scorer.
    Higher score = better journey for the given weights.
    """

    def score(self, journey: Journey, weights: WeightVector) -> float:
        """
        Compute utility score for a single journey.

        Formula:
          U = w_cost*(1-fare_norm) + w_time*(1-dur_norm)
            + w_transfers*(1-transfer_norm) + w_walking*(1-walk_norm)

        Range: [0.0, 1.0]
        """
        fare_norm     = _normalize(
            journey.total_fare_egp,        ALEX_NORM_STATS["fare_max"]
        )
        duration_norm = _normalize(
            journey.total_duration_minutes, ALEX_NORM_STATS["duration_max"]
        )
        transfer_norm = _normalize(
            float(journey.transfers),       ALEX_NORM_STATS["transfers_max"]
        )
        walking_norm  = _normalize(
            journey.total_walking_meters,   ALEX_NORM_STATS["walking_max"]
        )

        utility = (
            weights.cost      * (1.0 - fare_norm)
            + weights.time      * (1.0 - duration_norm)
            + weights.transfers * (1.0 - transfer_norm)
            + weights.walking   * (1.0 - walking_norm)
        )
        return round(utility, 6)

    def score_all(
        self,
        journeys: List[Journey],
        weights:  WeightVector,
    ) -> List[Tuple[Journey, float]]:
        """
        Score all journeys. Returns (journey, score) sorted descending.
        """
        scored = [(j, self.score(j, weights)) for j in journeys]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def get_reason(
        self,
        journey:  Journey,
        weights:  WeightVector,
        language: str = "ar",
    ) -> str:
        """
        Generate human-readable explanation for why this journey ranked well.
        Finds dominant weight → generates reason for that dimension.
        """
        weight_dict = {
            "cost":      weights.cost,
            "time":      weights.time,
            "transfers": weights.transfers,
            "walking":   weights.walking,
        }
        dominant = max(weight_dict, key=weight_dict.get)

        reasons_ar = {
            "cost": (
                f"أرخص طريق متاح بتكلفة {journey.total_fare_egp:.0f} جنيه"
            ),
            "time": (
                f"أسرع طريق بوقت {journey.total_duration_minutes:.0f} دقيقة"
            ),
            "transfers": (
                f"أقل تحويلات ({journey.transfers} تحويلة)"
            ),
            "walking": (
                f"أقل مشي ({journey.total_walking_meters:.0f} متر)"
            ),
        }
        reasons_en = {
            "cost": (
                f"Cheapest option at {journey.total_fare_egp:.0f} EGP"
            ),
            "time": (
                f"Fastest route at {journey.total_duration_minutes:.0f} min"
            ),
            "transfers": (
                f"Fewest transfers "
                f"({journey.transfers} transfer"
                f"{'s' if journey.transfers != 1 else ''})"
            ),
            "walking": (
                f"Least walking ({journey.total_walking_meters:.0f}m)"
            ),
        }

        reasons = reasons_ar if language == "ar" else reasons_en
        return reasons.get(dominant, "")