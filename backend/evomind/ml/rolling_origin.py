from __future__ import annotations

from collections.abc import Callable
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
    on_progress: Callable[[str], None] | None = None,
) -> RollingOriginResult:
    if len(cutoff_fractions) < 2:
        raise ValueError("Need at least 2 cutoff_fractions to form a rolling-origin fold.")
    if list(cutoff_fractions) != sorted(cutoff_fractions):
        raise ValueError("cutoff_fractions must be chronologically increasing.")

    def report_progress(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    fold_tables: list[tuple[str, pd.DataFrame]] = []
    n = len(cutoff_fractions)

    report_progress("Cloning repository…")
    with local_repo_path(repo) as path:
        start, end = commit_date_range(path)

        report_progress("Mining commit history…")
        mined = mine_repository(path, since=start)
        if not mined.records:
            raise ValueError(f"No source code found in '{repo}'. It may contain only documentation or configuration, or code in a language EvoMind can't read.")

        for i, fraction in enumerate(cutoff_fractions):
            cutoff = start + (end - start) * fraction
            horizon_end = cutoff + timedelta(days=horizon_days)

            report_progress(f"Reading code at cutoff {i + 1} of {n} ({fraction:.0%} through history)…")
            cutoff_commit = commit_at_or_before(path, cutoff)
            if cutoff_commit is None:
                raise ValueError(f"Could not resolve a commit at or before {cutoff.isoformat()}.")
            snapshots = read_files_at_commit(path, cutoff_commit)

            df = build_feature_table(mined, cutoff=cutoff, snapshots=snapshots, horizon_days=horizon_days)
            df = refine_labels_with_szz(df, mined.records, path, cutoff, horizon_end)
            fold_tables.append((cutoff.isoformat(), df))

    result = RollingOriginResult(repo=repo)
    fold_pairs = list(zip(fold_tables, fold_tables[1:]))
    for i, ((train_cutoff, train_df), (test_cutoff, test_df)) in enumerate(fold_pairs):
        if len(train_df) < 10 or train_df["is_bug_prone"].nunique() < 2:
            continue
        if len(test_df) < 10 or test_df["is_bug_prone"].nunique() < 2:
            continue

        report_progress(f"Evaluating fold {i + 1} of {len(fold_pairs)} (train → test)…")
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

    report_progress("Done.")
    return result
