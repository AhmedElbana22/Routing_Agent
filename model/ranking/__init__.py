"""
__init__.py — RankingLayer
Combines MNL and LambdaRank with confidence-based blending.
Public API for all ranking operations.

Strategy:
  1. Always compute MNL scores (fast, interpretable, always available)
  2. Try LTR if model loaded + confident
  3. Blend based on LTR confidence
  4. Apply hard constraints (return empty list if all filtered — agent handles it)
  5. Attach scores/ranks to journey copies (never mutate originals)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from model.intent.schema import Journey, RankingSource, WeightVector
from model.ranking.mnl import MNLScorer
from model.ranking.lambdarank import LambdaRankModel
import structlog

logger = structlog.get_logger(__name__)

#  Blending thresholds 
LTR_CONFIDENCE_THRESHOLD = 0.75   # above -> use LTR only
LTR_BLEND_WEIGHT         = 0.30   # below -> 70% MNL + 30% LTR


class RankingLayer:
    """
    Main ranking API — one instance shared across all requests.

    Returns new Journey objects (copies) with score/rank attached.
    Never mutates input journeys.
    """

    def __init__(self, auto_load_ltr: bool = True):
        self._mnl            = MNLScorer()
        self._ltr            = LambdaRankModel()
        self._ltr_available  = False

        if auto_load_ltr:
            self._ltr_available = self._ltr.load()
            if not self._ltr_available:
                logger.info(
                    "ltr_not_available_using_mnl_only",
                    hint="Train with RankingLayer.train_ltr() to enable LTR",
                )

    def rank(
        self,
        journeys:    List[Journey],
        weights:     WeightVector,
        constraints: Optional[list] = None,
        language:    str            = "ar",
        hour:        Optional[int]  = None,
    ) -> List[Journey]:
        """
        Rank journeys. Returns sorted list (best first).

        Constraint handling:
          - Journeys violating constraints are REMOVED from result
          - Returns EMPTY LIST if all violate constraints
          - agent.py detects empty list and handles fallback
          - (No silent constraint relaxation here)

        Args:
            journeys:    Raw journey list from routing engine
            weights:     User preference weights from Intent
            constraints: Hard constraints (fare/duration/transfers/walking)
            language:    "ar" | "en" for reason text generation
            hour:        Hour of day (default: now) for rush-hour features

        Returns:
            List[Journey] — new objects with score/rank/reason set
            Empty list if all journeys violate constraints
        """
        if not journeys:
            return []

        if hour is None:
            hour = datetime.now().hour

        #  Step 1: Apply hard constraints 
        # Returns [] if all filtered — agent.py handles this case
        if constraints:
            eligible = [j for j in journeys if j.satisfies_constraints(constraints)]
            filtered_out = len(journeys) - len(eligible)
            if filtered_out > 0:
                logger.info(
                    "journeys_filtered_by_constraints",
                    filtered_out=filtered_out,
                    remaining=len(eligible),
                )
            # Removed silent relaxation: if eligible is empty, return []
            # agent.py will detect this and re-rank without constraints
            if not eligible:
                return []
        else:
            eligible = journeys

        #  Step 2: MNL scores (always computed) 
        mnl_scored  = self._mnl.score_all(eligible, weights)
        mnl_scores  = np.array([score for _, score in mnl_scored])

        #  Step 3: LTR scores (if available and confident) 
        source       = RankingSource.MNL
        final_scores = mnl_scores

        if self._ltr_available and self._ltr.is_ready and len(eligible) >= 2:
            try:
                # Get LTR scores in original eligible order
                ltr_scores_raw = self._ltr.score(eligible, hour=hour, weights=weights)

                # Normalize LTR to [0, 1] to match MNL scale
                ltr_min, ltr_max = ltr_scores_raw.min(), ltr_scores_raw.max()
                if ltr_max > ltr_min:
                    ltr_norm = (ltr_scores_raw - ltr_min) / (ltr_max - ltr_min)
                else:
                    ltr_norm = np.full_like(ltr_scores_raw, 0.5)

                #  Re-order LTR scores to match mnl_scored order 
                # mnl_scored is sorted, eligible is original order
                # Build index: eligible[i] → i
                eligible_idx = {id(j): i for i, j in enumerate(eligible)}
                ltr_reordered = np.array([
                    ltr_norm[eligible_idx[id(journey)]]
                    for journey, _ in mnl_scored
                ])   

                confidence = self._ltr.get_confidence()

                if confidence >= LTR_CONFIDENCE_THRESHOLD:
                    final_scores = ltr_reordered
                    source       = RankingSource.LTR
                    logger.debug(
                        "using_ltr_ranking",
                        confidence=round(confidence, 3),
                    )
                else:
                    final_scores = (
                        (1.0 - LTR_BLEND_WEIGHT) * mnl_scores
                        + LTR_BLEND_WEIGHT        * ltr_reordered
                    )
                    source = RankingSource.BLENDED
                    logger.debug(
                        "using_blended_ranking",
                        confidence=round(confidence, 3),
                        ltr_weight=LTR_BLEND_WEIGHT,
                    )

            except Exception as e:
                logger.warning("ltr_scoring_failed", error=str(e))
                source       = RankingSource.MNL_FALLBACK
                final_scores = mnl_scores    # safe fallback

        #  Step 4: Sort by final scores 
        journey_list = [j for j, _ in mnl_scored]
        ranked_pairs = sorted(
            zip(journey_list, final_scores.tolist()),
            key=lambda x: x[1],
            reverse=True,
        )

        #  Step 5: Feature importance (for LTR/blended only) 
        feature_importance = {}
        if source in (RankingSource.LTR, RankingSource.BLENDED):
            try:
                feature_importance = self._ltr.get_feature_importance()
            except Exception:
                pass

        #  Step 6: Build result — COPIES not mutations 
        result = []
        for rank_idx, (journey, score) in enumerate(ranked_pairs):
            ranked_journey = journey.model_copy(update={   # ← fixed: was direct mutation
                "score":              round(score, 6),
                "rank":               rank_idx + 1,
                "ranking_source":     source,
                "rank_reason":        self._mnl.get_reason(journey, weights, language),
                "feature_importance": feature_importance,
            })
            result.append(ranked_journey)

        logger.info(
            "ranking_complete",
            n_input=len(journeys),
            n_eligible=len(eligible),
            n_ranked=len(result),
            source=source.value,
            top_score=round(result[0].score, 4) if result else 0,
        )
        for j, score in mnl_scored[:5]:
            logger.info("mnl_debug", 
                fare=j.total_fare_egp,
                duration=j.total_duration_minutes,
                score=score
            )

        return result

    def train_ltr(
        self,
        n_queries:          int = 500,
        journeys_per_query: int = 6,
    ) -> dict:
        """Train LTR model and enable it for future ranking."""
        metrics = self._ltr.train(
            n_queries=n_queries,
            journeys_per_query=journeys_per_query,
            save=True,
        )
        self._ltr_available = self._ltr.is_ready
        logger.info(
            "ltr_training_complete",
            available=self._ltr_available,
            metrics=metrics,
        )
        return metrics