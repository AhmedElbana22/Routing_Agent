"""
lambdarank.py
LambdaRank LTR model using XGBoost Booster API.  

Features (8): duration, fare, transfers, steps,
              walking, hour, morning_rush, evening_rush

Training: synthetic pairwise preference data
          generated from MNL scores as ground truth.

Confidence threshold → blend or override MNL.
"""

from __future__ import annotations

import json
import pickle
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import uuid
import random

import numpy as np
import xgboost as xgb
from sklearn.preprocessing import StandardScaler

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from model.intent.schema import Journey, Step, TransportMode, WeightVector
from model.ranking.mnl import MNLScorer
import structlog

logger = structlog.get_logger(__name__)

#  Model file paths — absolute, relative to this file 
_RANKING_DIR = Path(__file__).parent.resolve()

FEATURE_NAMES = [
    "duration_minutes",
    "fare_egp",
    "transfers",
    "num_steps",
    "walking_meters",
    "hour_of_day",
    "is_morning_rush",
    "is_evening_rush",
    "w_cost",
    "w_time",
    "w_transfers",
    "w_walking",
]



# Feature extraction



def extract_features(
    journey: Journey,
    hour: Optional[int] = None,
    weights: Optional[WeightVector] = None,   
) -> np.ndarray:
    if hour is None:
        hour = datetime.now().hour

    # Default to balanced if no weights provided
    w = weights or WeightVector()

    return np.array([
        journey.total_duration_minutes,
        journey.total_fare_egp,
        float(journey.transfers),
        float(len(journey.steps)),
        journey.total_walking_meters,
        float(hour),
        float(7  <= hour <= 9),
        float(17 <= hour <= 19),
        # Weight features — tell LTR what user cares about  
        w.cost,
        w.time,
        w.transfers,
        w.walking,
    ], dtype=np.float32)


def extract_features_batch(
    journeys: List[Journey],
    hour: Optional[int] = None,
    weights: Optional[WeightVector] = None,    
) -> np.ndarray:
    if hour is None:
        hour = datetime.now().hour
    return np.stack(
        [extract_features(j, hour, weights) for j in journeys],
        axis=0
    )


# Synthetic training data generator



class SyntheticDataGenerator:
    """
    Generates synthetic journey data for LTR training.
    MNL scores act as ground truth relevance labels.
    """

    def __init__(
        self,
        n_queries:          int = 500,
        journeys_per_query: int = 6,
    ):
        self.n_queries          = n_queries
        self.journeys_per_query = journeys_per_query
        self._mnl               = MNLScorer()

    def _random_journey(self) -> Journey:
        """
        Generate a plausible synthetic journey.
        Uses correct Journey schema (lat/lon not stop IDs).
        """
        transfers = random.randint(0, 3)
        duration  = random.uniform(10, 90) + transfers * 5
        fare      = random.uniform(2, 25)    # Alexandria fare range
        walking   = random.uniform(0, 1200)
        n_steps   = transfers + 1 + random.randint(0, 1)

        steps = [
            Step(
                mode=TransportMode.MICROBUS,
                line_id=str(random.randint(1, 100)),   
                line_name=f"Microbus {random.randint(1, 100)}",
                from_stop_id=str(random.randint(1, 500)),  
                from_stop_name=f"Stop {random.randint(1, 500)}",
                to_stop_id=str(random.randint(1, 500)),   
                to_stop_name=f"Stop {random.randint(1, 500)}",
                duration_minutes=duration / n_steps,
                distance_meters=random.uniform(300, 4000),
                fare_egp=fare / n_steps,
            )
            for _ in range(n_steps)
        ]

        # use lat/lon not stop IDs
        return Journey(
            journey_id=str(uuid.uuid4()),
            origin_lat=31.2 + random.uniform(-0.1, 0.1),    # Alexandria lat range
            origin_lon=29.9 + random.uniform(-0.1, 0.1),    # Alexandria lon range
            destination_lat=31.2 + random.uniform(-0.1, 0.1),
            destination_lon=29.9 + random.uniform(-0.1, 0.1),
            steps=steps,
            total_duration_minutes=duration,
            total_fare_egp=fare,
            transfers=transfers,
            total_walking_meters=walking,
        )

    def _random_weights(self) -> WeightVector:
        """Generate random normalized weight vector."""
        w     = [random.random() for _ in range(4)]
        total = sum(w)
        return WeightVector(
            cost=w[0]      / total,
            time=w[1]      / total,
            transfers=w[2] / total,
            walking=w[3]   / total,
        )

    def generate(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Generate training data.

        Returns:
            X:      (n_samples, 8) feature matrix
            y:      (n_samples,)   relevance labels [0-3]
            groups: (n_queries,)   group sizes for XGBoost ranker
        """
        X_list: list = []
        y_list: list = []
        groups: list = []

        for _ in range(self.n_queries):
            weights  = self._random_weights()
            journeys = [self._random_journey()
                        for _ in range(self.journeys_per_query)]

            scored = self._mnl.score_all(journeys, weights)
            n      = len(scored)

            for rank, (journey, _) in enumerate(scored):
                label = min(max(0, n - 1 - rank), 3)
                X_list.append(extract_features(journey, weights=weights))  # pass weights
                y_list.append(float(label))

            groups.append(n)

        X      = np.stack(X_list, axis=0)
        y      = np.array(y_list,  dtype=np.float32)
        groups = np.array(groups,  dtype=np.int32)

        logger.info(
            "synthetic_data_generated",
            n_samples=len(X),
            n_queries=self.n_queries,
        )
        return X, y, groups


 
# LambdaRank model
 


class LambdaRankModel:
    """
    XGBoost LambdaRank model.
    Uses Booster API (xgb.train) consistently throughout.
    Paths are absolute (relative to this file).
    """

    # absolute paths using __file__
    MODEL_PATH  = _RANKING_DIR / "lambdarank_model.pkl"
    SCALER_PATH = _RANKING_DIR / "lambdarank_scaler.pkl"
    META_PATH   = _RANKING_DIR / "lambdarank_meta.json"

    def __init__(self):
        self._model:      Optional[xgb.Booster]       = None   
        self._scaler:     Optional[StandardScaler]     = None
        self._trained:    bool                         = False
        self._train_ndcg: float                        = 0.0

    def train(
        self,
        n_queries:          int  = 500,
        journeys_per_query: int  = 6,
        save:               bool = True,
    ) -> Dict[str, float]:
        """Train on synthetic data. Returns metrics dict."""
        logger.info(
            "lambdarank_training_start",
            n_queries=n_queries,
            journeys_per_query=journeys_per_query,
        )

        #  1. Generate data 
        gen         = SyntheticDataGenerator(n_queries, journeys_per_query)
        X, y, groups = gen.generate()

        #  2. Scale features 
        self._scaler = StandardScaler()
        X_scaled     = self._scaler.fit_transform(X)

        #  3. Query-aware train/val split (80/20) 
        split_q = int(len(groups) * 0.8)
        split_s = int(groups[:split_q].sum())

        X_train, y_train = X_scaled[:split_s], y[:split_s]
        X_val,   y_val   = X_scaled[split_s:], y[split_s:]
        g_train          = groups[:split_q]
        g_val            = groups[split_q:]

        #  4. Build DMatrix 
        dtrain = xgb.DMatrix(X_train, label=y_train,
                             feature_names=FEATURE_NAMES)
        dtrain.set_group(g_train)

        dval   = xgb.DMatrix(X_val, label=y_val,
                             feature_names=FEATURE_NAMES)
        dval.set_group(g_val)

        #  5. Train with Booster API 
        params = {
            "objective":        "rank:ndcg",
            "eval_metric":      "ndcg@3",
            "eta":              0.1,
            "max_depth":        4,
            "min_child_weight": 1,
            "subsample":        0.8,
            "colsample_bytree": 0.8,
            "lambda":           1.0,
            "alpha":            0.1,
            "tree_method":      "hist",
            "seed":             42,
        }

        evals_result: Dict = {}
        self._model = xgb.train(
            params,
            dtrain,
            num_boost_round=200,
            evals=[(dtrain, "train"), (dval, "val")],
            evals_result=evals_result,
            early_stopping_rounds=20,
            verbose_eval=False,
        )   # returns xgb.Booster — consistent with type hint

        val_ndcg        = evals_result["val"]["ndcg@3"][-1]
        train_ndcg      = evals_result["train"]["ndcg@3"][-1]
        self._train_ndcg = val_ndcg
        self._trained    = True

        metrics = {
            "train_ndcg@3": round(train_ndcg, 4),
            "val_ndcg@3":   round(val_ndcg, 4),
            "n_trees":      self._model.best_iteration + 1,
        }
        logger.info("lambdarank_training_complete", **metrics)

        if save:
            self._save()

        return metrics

    def _save(self) -> None:
        """Save model, scaler, metadata to absolute paths."""
        self.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

        with open(self.MODEL_PATH,  "wb") as f:
            pickle.dump(self._model,   f)
        with open(self.SCALER_PATH, "wb") as f:
            pickle.dump(self._scaler,  f)

        meta = {
            "feature_names": FEATURE_NAMES,
            "val_ndcg":      self._train_ndcg,
            "trained":       True,
        }
        with open(self.META_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        logger.info("lambdarank_saved", path=str(self.MODEL_PATH))

    def load(self) -> bool:
        """Load saved model. Returns True if successful."""
        try:
            if not self.MODEL_PATH.exists():
                logger.warning(
                    "lambdarank_model_not_found",
                    path=str(self.MODEL_PATH),
                )
                return False

            with open(self.MODEL_PATH,  "rb") as f:
                self._model  = pickle.load(f)
            with open(self.SCALER_PATH, "rb") as f:
                self._scaler = pickle.load(f)
            with open(self.META_PATH,   "r", encoding="utf-8") as f:
                meta = json.load(f)

            self._train_ndcg = meta.get("val_ndcg", 0.0)
            self._trained    = True

            logger.info(
                "lambdarank_loaded",
                val_ndcg=self._train_ndcg,
                path=str(self.MODEL_PATH),
            )
            return True

        except Exception as e:
            logger.error("lambdarank_load_failed", error=str(e))
            return False

    def score(
        self,
        journeys: List[Journey],
        hour: Optional[int] = None,
        weights: Optional[WeightVector] = None,   # ← NEW
    ) -> np.ndarray:
        if not self._trained or self._model is None:
            raise RuntimeError("Model not trained. Call train() or load() first.")

        X        = extract_features_batch(journeys, hour, weights)   # ← pass weights
        X_scaled = self._scaler.transform(X)
        dmatrix  = xgb.DMatrix(X_scaled, feature_names=FEATURE_NAMES)
        return self._model.predict(dmatrix)

    def get_confidence(self) -> float:
        """
        Confidence based on validation NDCG.
        Maps NDCG [0.5, 1.0] → confidence [0.0, 1.0]
        """
        if not self._trained:
            return 0.0
        return max(0.0, min(1.0, (self._train_ndcg - 0.5) * 2.0))

    def get_feature_importance(self) -> Dict[str, float]:
        """
        Return normalized feature importance dict.
        Uses named features (passed to DMatrix) for reliable key mapping.
        """
        if not self._trained or self._model is None:
            return {}
        try:
            # get_score returns {feature_name: importance} when features are named
            scores = self._model.get_score(importance_type="gain")
            total  = sum(scores.values()) or 1.0
            return {
                name: round(scores.get(name, 0.0) / total, 4)
                for name in FEATURE_NAMES
            }
        except Exception as e:
            logger.warning("feature_importance_failed", error=str(e))
            return {}

    @property
    def is_ready(self) -> bool:
        return self._trained and self._model is not None