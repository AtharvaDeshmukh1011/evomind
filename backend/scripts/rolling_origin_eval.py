from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evomind.ml.rolling_origin import run_rolling_origin_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description="Rolling-origin walk-forward evaluation.")
    parser.add_argument("--repo", default="https://github.com/pallets/flask", help="Local path or Git URL")
    parser.add_argument("--horizon-days", type=int, default=365)
    parser.add_argument(
        "--cutoffs", type=float, nargs="+", default=[0.5, 0.65, 0.8],
        help="Chronologically increasing fractions through history, e.g. 0.5 0.65 0.8",
    )
    args = parser.parse_args()

    print(f"Rolling-origin evaluation of {args.repo}")
    print(f"Cutoffs: {args.cutoffs}  (this repeats the per-cutoff pipeline work once per fold — slower than /analyze)")

    result = run_rolling_origin_evaluation(
        repo=args.repo, horizon_days=args.horizon_days, cutoff_fractions=tuple(args.cutoffs)
    )

    print(f"\n{len(result.folds)} fold(s) evaluated:\n")
    for fold in result.folds:
        print(f"  Train @ {fold.train_cutoff}  ({fold.train_files} files)")
        print(f"  Test  @ {fold.test_cutoff}  ({fold.test_files} files)")
        for r in fold.report.results:
            print(f"    {r.model_name:28s} P={r.precision:.3f} R={r.recall:.3f} F1={r.f1:.3f} ROC-AUC={r.roc_auc:.3f}")
        print()

    print("=== Cross-fold summary (mean ± std) ===")
    for model, stats in result.summary().items():
        f1_std = stats["f1_std"] if stats["f1_std"] == stats["f1_std"] else 0.0
        auc_std = stats["roc_auc_std"] if stats["roc_auc_std"] == stats["roc_auc_std"] else 0.0
        print(f"  {model:28s} F1={stats['f1_mean']:.3f}±{f1_std:.3f}  ROC-AUC={stats['roc_auc_mean']:.3f}±{auc_std:.3f}")


if __name__ == "__main__":
    main()
