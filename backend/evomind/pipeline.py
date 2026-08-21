"""Shared orchestration: mine -> extract features -> train -> score.

Used by both the CLI script (scripts/run_pipeline.py) and the FastAPI
service (evomind/api/main.py) so the two entry points can't drift apart.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from evomind.features.feature_builder import build_feature_table
from evomind.ingestion.git_miner import mine_repository
from evomind.ingestion.repo_source import local_repo_path
from evomind.ml.train import FEATURE_COLUMNS, TrainingReport, train_and_evaluate


def _commit_date_range(path: str) -> tuple[datetime, datetime]:
    """Min/max commit author dates, via `git log` directly.

    Avoids a full PyDriller traversal (which parses every commit's diffs)
    just to learn the repo's date span. Scans every author date rather than
    trusting the first/last log entries, since commit order (by commit date)
    and author-date order can diverge under rebases/backports.
    """
    out = subprocess.run(
        ["git", "-C", path, "log", "--format=%aI"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    dates = [datetime.fromisoformat(line).replace(tzinfo=None) for line in out.splitlines() if line]
    if not dates:
        raise ValueError("No commits found in repository.")
    return min(dates), max(dates)


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


def run_pipeline(
    repo: str,
    horizon_days: int = 365,
    train_fraction: float = 0.65,
) -> PipelineResult:
    with local_repo_path(repo) as path:
        start, end = _commit_date_range(path)
        cutoff = start + (end - start) * train_fraction

        # Single traversal captures both the training-time cutoff snapshot
        # and the latest (current) snapshot of every file.
        mined = mine_repository(path, snapshot_asof=cutoff, track_latest_snapshot=True)

    if not mined.records:
        raise ValueError(f"No source files mined from '{repo}'. Check the repo URL/path.")

    train_df = build_feature_table(mined, cutoff=cutoff, horizon_days=horizon_days)

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
        mined, cutoff=end, horizon_days=0, snapshots=mined.latest_snapshots
    )
    current_df["risk_score"] = report.model.predict_proba(current_df[FEATURE_COLUMNS])[:, 1]
    scores = current_df[["file_path", "risk_score"]].sort_values(
        "risk_score", ascending=False
    )

    return PipelineResult(
        repo=repo,
        cutoff=cutoff.isoformat(),
        horizon_days=horizon_days,
        feature_table=train_df,
        training_report=report,
        file_risk_scores=scores,
        current_metrics=current_df,
        latest_snapshots=mined.latest_snapshots,
    )
