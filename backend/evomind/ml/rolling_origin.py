"""Rolling-origin (walk-forward) time-based evaluation.

The main pipeline (evomind/pipeline.py) evaluates with a single random
train/test split within one snapshot — fast enough for interactive
dashboard use, but that split has nothing to do with time, so it never
actually tests whether a model trained on older data still holds up on
newer, unseen data. Rolling-origin does exactly that: train at an earlier
cutoff, evaluate purely on a later period the model never saw. This is the
evaluation protocol closer to what rigorous defect-prediction papers use
(e.g. the time-dependent methods in Robredo et al., 2024), and it directly
answers the question a single split can't: is performance stable across
time, or did we get lucky (or unlucky) with one arbitrary split?

Deliberately NOT part of the interactive /analyze path: it repeats the
expensive per-cutoff work (tree read + code metrics for every file) once
per fold, so it multiplies analysis time by roughly the fold count. Meant
for generating a report-quality evaluation via scripts/rolling_origin_eval.py,
not for every dashboard click.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import pandas as pd

from evomind.features.feature_builder import build_feature_table
from evomind.ingestion.git_miner import mine_repository
from evomind.ingestion.repo_source import local_repo_path
from evomind.ingestion.tree_snapshot import commit_at_or_before, commit_date_range, read_files_at_commit
from evomind.labeling.szz import refine_labels_with_szz
from evomind.ml.train import TrainingReport, train_on_evaluate_on


@dataclass
class FoldResult:
    train_cutoff: str
    test_cutoff: str
    train_files: int
    test_files: int
    report: TrainingReport


@dataclass
class RollingOriginResult:
    repo: str
    folds: list[FoldResult] = field(default_factory=list)

    def summary(self) -> dict[str, dict[str, float]]:
        """Mean/std F1 and ROC-AUC per model across folds — the headline
        robustness numbers: consistent metrics across folds mean the model
        generalizes across time, not just within one arbitrary split."""
        rows = [
            {"model": r.model_name, "f1": r.f1, "roc_auc": r.roc_auc}
            for fold in self.folds
            for r in fold.report.results
        ]
        if not rows:
            return {}
        df = pd.DataFrame(rows)
        agg = df.groupby("model").agg(["mean", "std"])
        return {
            model: {f"{metric}_{stat}": agg.loc[model, (metric, stat)] for metric in ("f1", "roc_auc") for stat in ("mean", "std")}
            for model in agg.index
        }


def run_rolling_origin_evaluation(
    repo: str,
    horizon_days: int = 365,
    cutoff_fractions: tuple[float, ...] = (0.5, 0.65, 0.8),
) -> RollingOriginResult:
    """Builds a feature table at each fraction in `cutoff_fractions`
    (chronologically increasing, each independently SZZ-refined), then
    evaluates every adjacent pair as a fold: train on fold i's data, test
    purely on fold i+1's — a later, non-overlapping period.
    """
    if len(cutoff_fractions) < 2:
        raise ValueError("Need at least 2 cutoff_fractions to form a rolling-origin fold.")
    if list(cutoff_fractions) != sorted(cutoff_fractions):
        raise ValueError("cutoff_fractions must be chronologically increasing.")

    fold_tables: list[tuple[str, pd.DataFrame]] = []

    with local_repo_path(repo) as path:
        start, end = commit_date_range(path)
        mined = mine_repository(path)
        if not mined.records:
            raise ValueError(f"No source files mined from '{repo}'. Check the repo URL/path.")

        for fraction in cutoff_fractions:
            cutoff = start + (end - start) * fraction
            horizon_end = cutoff + timedelta(days=horizon_days)

            cutoff_commit = commit_at_or_before(path, cutoff)
            if cutoff_commit is None:
                raise ValueError(f"Could not resolve a commit at or before {cutoff.isoformat()}.")
            snapshots = read_files_at_commit(path, cutoff_commit)

            df = build_feature_table(mined, cutoff=cutoff, snapshots=snapshots, horizon_days=horizon_days)
            df = refine_labels_with_szz(df, mined.records, path, cutoff, horizon_end)
            fold_tables.append((cutoff.isoformat(), df))

    result = RollingOriginResult(repo=repo)
    for (train_cutoff, train_df), (test_cutoff, test_df) in zip(fold_tables, fold_tables[1:]):
        if len(train_df) < 10 or train_df["is_bug_prone"].nunique() < 2:
            continue
        if len(test_df) < 10 or test_df["is_bug_prone"].nunique() < 2:
            continue

        report = train_on_evaluate_on(train_df, test_df)
        result.folds.append(
            FoldResult(
                train_cutoff=train_cutoff,
                test_cutoff=test_cutoff,
                train_files=len(train_df),
                test_files=len(test_df),
                report=report,
            )
        )

    if not result.folds:
        raise ValueError(
            "No fold had enough labeled data to evaluate — try a larger repo, "
            "a longer horizon_days, or fewer/wider-spaced cutoff_fractions."
        )

    return result
