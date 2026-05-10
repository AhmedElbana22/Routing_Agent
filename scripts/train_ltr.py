"""
Script to train the LambdaRank model.
Run once after routing engine is set up.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from model.ranking import RankingLayer

if __name__ == "__main__":
    print("Training LambdaRank model...")
    ranking_layer = RankingLayer(auto_load_ltr=False)
    metrics = ranking_layer.train_ltr(
        n_queries=2000,
        journeys_per_query=8,
    )
    print("Training complete!")
    print(f"  Train NDCG@3: {metrics['train_ndcg@3']}")
    print(f"  Val   NDCG@3: {metrics['val_ndcg@3']}")
    print(f"  Trees:        {metrics['n_trees']}")