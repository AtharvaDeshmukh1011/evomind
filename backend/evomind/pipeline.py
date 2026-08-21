"""Shared orchestration: mine -> extract features -> train -> score.

Used by both the CLI script (scripts/run_pipeline.py) and the FastAPI
service (evomind/api/main.py) so the two entry points can't drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from evomind.architecture.dependency_graph import (
    DependencyGraph,
    build_dependency_graph,
    compute_coupling,
    find_cyclic_groups,
)
from evomind.features.feature_builder import build_feature_table
from evomind.ingestion.git_miner import mine_repository
from evomind.ingestion.repo_source import local_repo_path
from evomind.ingestion.tree_snapshot import commit_at_or_before, commit_date_range, read_files_at_commit
from evomind.labeling.szz import refine_labels_with_szz
from evomind.ml.train import FEATURE_COLUMNS, TrainingReport, train_and_evaluate


@dataclass
class PipelineResult:
    repo: str
    cutoff: str
    horizon_days: int
    feature_table: pd.DataFrame
    training_report: TrainingReport
    file_risk_scores: pd.DataFrame
    current_metrics: pd.DataFrame  # file_path + FEATURE_COLUMNS + risk_score, for recommendations
    latest_snapshots: dict[str, str]  # file_path -> current source content
    dependency_graph: DependencyGraph
    coupling: list  # list[CouplingMetrics]
    cyclic_groups: list[list[str]]


def run_pipeline(
    repo: str,
    horizon_days: int = 365,
    train_fraction: float = 0.65,
) -> PipelineResult:
    with local_repo_path(repo) as path:
        start, end = commit_date_range(path)
        cutoff = start + (end - start) * train_fraction
        horizon_end = cutoff + timedelta(days=horizon_days)

        mined = mine_repository(path)

        if not mined.records:
            raise ValueError(f"No source files mined from '{repo}'. Check the repo URL/path.")

        # Exact tree reads at a resolved commit, not a chronological diff
        # replay — see tree_snapshot.py for why the replay approach silently
        # corrupts content under non-linear history (a branch predating a
        # rename, merged after it, "resurrects" the renamed-away path).
        cutoff_commit = commit_at_or_before(path, cutoff)
        if cutoff_commit is None:
            raise ValueError(
                f"Could not resolve a commit at or before {cutoff.isoformat()} in '{repo}'."
            )
        cutoff_snapshots = read_files_at_commit(path, cutoff_commit)
        latest_snapshots = read_files_at_commit(path, "HEAD")

        train_df = build_feature_table(mined, cutoff=cutoff, snapshots=cutoff_snapshots, horizon_days=horizon_days)

        # SZZ needs `git blame`/`git diff` against the local clone, so this
        # has to run before the `with` block exits and the clone is cleaned
        # up. Keeps only the labels whose underlying defect actually existed
        # at cutoff — see szz.py for why the naive heuristic overcounts.
        train_df = refine_labels_with_szz(train_df, mined.records, path, cutoff, horizon_end)

    if len(train_df) < 20 or train_df["is_bug_prone"].nunique() < 2:
        raise ValueError(
            f"Only {len(train_df)} files / "
            f"{train_df['is_bug_prone'].nunique()} label classes after feature "
            "extraction — not enough signal to train. Try a larger repo, "
            "longer horizon_days, or an earlier train_fraction."
        )

    report = train_and_evaluate(train_df)

    # Score the repo's current state (as of `end`) with no future horizon to
    # label against — this is the actual "predict what's risky now" output.
    current_df = build_feature_table(
        mined, cutoff=end, snapshots=latest_snapshots, horizon_days=0
    )
    current_df["risk_score"] = report.model.predict_proba(current_df[FEATURE_COLUMNS])[:, 1]
    scores = current_df[["file_path", "risk_score"]].sort_values(
        "risk_score", ascending=False
    )

    dep_graph = build_dependency_graph(latest_snapshots)
    coupling = compute_coupling(dep_graph)
    cyclic_groups = find_cyclic_groups(dep_graph)

    return PipelineResult(
        repo=repo,
        cutoff=cutoff.isoformat(),
        horizon_days=horizon_days,
        feature_table=train_df,
        training_report=report,
        file_risk_scores=scores,
        current_metrics=current_df,
        latest_snapshots=latest_snapshots,
        dependency_graph=dep_graph,
        coupling=coupling,
        cyclic_groups=cyclic_groups,
    )
