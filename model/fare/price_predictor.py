"""
price_predictor.py
Fare prediction using trained linear regression model (model.pkl).

Model formula:
  fare = ceil(intercept + β_distance × distance + β_passengers × passengers)

Features:
  distance   -> route distance in METERS (from route_geometry.geom_4326)
  passengers -> estimated passenger count (mode-based default, no real-time data)

Returns:
  Integer EGP (ceiling of linear prediction)
"""

from __future__ import annotations

import math
import os
import warnings
from pathlib import Path
from typing import Optional

from joblib import load

warnings.filterwarnings("ignore")


# Mode-based default passenger counts  
# Used when real-time passenger data is unavailable.
# Based on typical vehicle capacity in Alexandria.
MODE_DEFAULT_PASSENGERS: dict = {
    "microbus": 14,    # standard microbus capacity
    "bus":      40,    # standard bus
    "tram":     80,    # Alexandria tram
    "metro":    120,   # metro car (per car)
    "walk":     1,     # walking — 1 person
}
DEFAULT_PASSENGERS = 14   # fallback if mode unknown


class TripPricePredictor:
    """
    Predicts trip fare using trained linear regression.

    Usage:
        predictor = TripPricePredictor()
        fare = predictor.predict(distance=5200.0, passengers=14)
        # -> integer EGP

        # Or with mode-aware passengers:
        fare = predictor.predict_for_mode(distance=5200.0, mode="microbus")
    """

    def __init__(self, model_path: Optional[str] = None):
        """
        Load model.pkl from same directory as this file.

        Args:
            model_path: Override path to model.pkl.
                        Defaults to model/fare/model.pkl
        """
        if model_path is None:
            model_path = os.path.join(
                os.path.dirname(__file__), "model.pkl"
            )

        if not Path(model_path).exists():
            raise FileNotFoundError(
                f"Fare model not found at: {model_path}\n"
                f"Make sure model.pkl is in model/fare/"
            )

        self.model = load(model_path)
        self.intercept = self.model.intercept_
        self.beta_distance, self.beta_passengers = self.model.coef_

        self._model_path = model_path

    def predict(self, distance: float, passengers: int) -> int:
        """
        Predict fare for a trip.

        Args:
            distance:   Route distance in METERS
                        (from ST_Length(geom_4326::geography))
            passengers: Estimated passenger count

        Returns:
            Fare in EGP (integer, ceiling of linear prediction)

        Example:
            predict(distance=5200.0, passengers=14) → 8
        """
        raw = (
            self.intercept
            + self.beta_distance   * distance
            + self.beta_passengers * passengers
        )
        return math.ceil(raw)

    def predict_for_mode(
        self,
        distance:   float,
        mode:       Optional[str] = None,
        passengers: Optional[int] = None,
    ) -> int:
        """
        Predict fare using mode-based default passengers.

        Convenience method for db_tool.py — avoids needing
        real-time passenger data.

        Args:
            distance:   Route distance in METERS
            mode:       Transport mode string ("microbus", "bus", etc.)
                        Uses MODE_DEFAULT_PASSENGERS lookup.
            passengers: Override passenger count (ignores mode if set)

        Returns:
            Fare in EGP (integer)

        Example:
            predict_for_mode(distance=5200.0, mode="microbus") -> 8
            predict_for_mode(distance=5200.0, passengers=20)   -> 9
        """
        if passengers is None:
            passengers = MODE_DEFAULT_PASSENGERS.get(
                (mode or "").lower(),
                DEFAULT_PASSENGERS,
            )
        return self.predict(distance=distance, passengers=passengers)

    @property
    def coefficients(self) -> dict:
        """Return model coefficients for debugging/logging."""
        return {
            "intercept":        self.intercept,
            "beta_distance":    self.beta_distance,
            "beta_passengers":  self.beta_passengers,
        }

    def __repr__(self) -> str:
        return (
            f"TripPricePredictor("
            f"intercept={self.intercept:.4f}, "
            f"β_dist={self.beta_distance:.6f}, "
            f"β_pass={self.beta_passengers:.4f})"
        )