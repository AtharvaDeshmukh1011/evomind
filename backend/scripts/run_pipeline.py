"""End-to-end EvoMind pipeline: mine a repo, build features, train, evaluate.

Usage:
    .venv/Scripts/python.exe scripts/run_pipeline.py --repo https://github.com/pallets/flask
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evomind.pipeline import run_pipeline

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the EvoMind bug-proneness pipeline on a repo.")
    parser.add_argument("--repo", default="https://github.com/pallets/flask", help="Local path or Git URL")
    parser.add_argument("--horizon-days", type=int, default=365, help="Future window used to label bug-proneness")
    parser.add_argument("--train-fraction", type=float, default=0.65, help="Fraction of history used before the cutoff")
    parser.add_argument("--out-name", default="flask", help="Prefix for saved artifacts")
    parser.add_argument("--top-n", type=int, default=10, help="How many top-risk files to print")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    print(f"Mining {args.repo} and training (this walks full commit history twice) ...")
    result = run_pipeline(
        repo=args.repo,
        horizon_days=args.horizon_days,
        train_fraction=args.train_fraction,
    )

    print(f"\nCutoff: {result.cutoff}  |  horizon: {result.horizon_days} days")
    print(f"Training set: {len(result.feature_table)} files, "
          f"{result.feature_table['is_bug_prone'].sum()} labeled bug-prone "
          f"({result.feature_table['is_bug_prone'].mean():.1%})")

    features_path = DATA_DIR / f"{args.out_name}_features.csv"
    result.feature_table.to_csv(features_path, index=False)

    scores_path = DATA_DIR / f"{args.out_name}_risk_scores.csv"
    result.file_risk_scores.to_csv(scores_path, index=False)

    print("\n=== Evaluation (held-out test split) ===")
    for r in result.training_report.results:
        print(
            f"  {r.model_name:28s} "
            f"P={r.precision:.3f}  R={r.recall:.3f}  F1={r.f1:.3f}  "
            f"ROC-AUC={r.roc_auc:.3f}  AP={r.average_precision:.3f}  "
            f"(n={r.n_test}, positive_rate={r.positive_rate:.1%})"
        )
    print(f"  Best model by F1: {result.training_report.best_model_name}")

    print("\n=== Top feature importances (Random Forest) ===")
    for name, importance in list(result.training_report.feature_importances.items())[:8]:
        print(f"  {name:28s} {importance:.3f}")

    print(f"\n=== Top {args.top_n} highest-risk files right now ===")
    for _, row in result.file_risk_scores.head(args.top_n).iterrows():
        print(f"  {row['risk_score']:.3f}  {row['file_path']}")

    print(f"\nSaved feature table -> {features_path}")
    print(f"Saved risk scores   -> {scores_path}")


if __name__ == "__main__":
    main()
