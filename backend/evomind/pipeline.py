from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePosixPath

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
from evomind.labeling.llm_szz import AssessmentStats, refine_labels_with_llm_szz
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
    current_metrics: pd.DataFrame
    latest_snapshots: dict[str, str]
    dependency_graph: DependencyGraph
    coupling: list
    cyclic_groups: list[list[str]]
    llm_szz_stats: AssessmentStats | None = None


def _no_analysable_files_message(repo: str, mined, cutoff: datetime) -> str:
    found = sorted(
        {PurePosixPath(rec.file_path.replace("\\", "/")).suffix for rec in mined.records}
        - {""}
    )
    return (
        f"No analysable files remain for '{repo}' at the "
        f"{cutoff.date().isoformat()} cutoff. Mining produced "
        f"{len(mined.records)} change records covering {len(found)} supported "
        f"extension(s) ({', '.join(found) if found else 'none'}), but none of "
        "those files existed at the cutoff with measurable code. This usually "
        "means the repository is written in a language EvoMind cannot measure "
        "— Elixir and Haskell, for example, are not supported. Supported "
        "languages include Python, JavaScript/TypeScript, Java, Go, C/C++, C#, "
        "Ruby, PHP, Rust, Kotlin, Swift and Dart."
    )


def run_pipeline(
    repo: str,
    horizon_days: int = 365,
    train_fraction: float = 0.65,
    on_progress: Callable[[str], None] | None = None,
    use_llm_szz: bool = False,
) -> PipelineResult:
    def report_progress(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    with local_repo_path(repo) as path:
        report_progress("Cloning repository…")
        start, end = commit_date_range(path)
        cutoff = start + (end - start) * train_fraction
        horizon_end = cutoff + timedelta(days=horizon_days)

        report_progress("Mining commit history…")
        mined = mine_repository(path)

        if not mined.records:
            raise ValueError(f"No source files mined from '{repo}'. Check the repo URL/path.")

        report_progress("Reading code at the training cutoff…")
        cutoff_commit = commit_at_or_before(path, cutoff)
        if cutoff_commit is None:
            raise ValueError(
                f"Could not resolve a commit at or before {cutoff.isoformat()} in '{repo}'."
            )
        cutoff_snapshots = read_files_at_commit(path, cutoff_commit)

        report_progress("Reading the repository's current state…")
        latest_snapshots = read_files_at_commit(path, "HEAD")

        report_progress("Computing code metrics and building features…")
        train_df = build_feature_table(mined, cutoff=cutoff, snapshots=cutoff_snapshots, horizon_days=horizon_days)

        if train_df.empty:
            raise ValueError(_no_analysable_files_message(repo, mined, cutoff))

        llm_szz_stats: AssessmentStats | None = None
        if use_llm_szz:
            report_progress("Tracing bug-inducing commits (SZZ + LLM re-ranking)…")
            train_df, llm_szz_stats = refine_labels_with_llm_szz(
                train_df, mined.records, path, cutoff, horizon_end
            )
        else:
            report_progress("Tracing bug-inducing commits (SZZ)…")
            train_df = refine_labels_with_szz(train_df, mined.records, path, cutoff, horizon_end)

    if train_df.empty:
        raise ValueError(_no_analysable_files_message(repo, mined, cutoff))

    label_classes = train_df["is_bug_prone"].nunique()
    if len(train_df) < 20 or label_classes < 2:
        raise ValueError(
            f"Only {len(train_df)} files / {label_classes} label classes after "
            "feature extraction — not enough signal to train. Try a larger repo, "
            "longer horizon_days, or an earlier train_fraction."
        )

    report_progress("Training Random Forest and Logistic Regression models…")
    report = train_and_evaluate(train_df)

    report_progress("Scoring the repository's current files…")
    current_df = build_feature_table(
        mined, cutoff=end, snapshots=latest_snapshots, horizon_days=0
    )
    current_df["risk_score"] = report.model.predict_proba(current_df[FEATURE_COLUMNS])[:, 1]
    scores = current_df[["file_path", "risk_score"]].sort_values(
        "risk_score", ascending=False
    )

    report_progress("Building the dependency graph…")
    dep_graph = build_dependency_graph(latest_snapshots)
    coupling = compute_coupling(dep_graph)
    cyclic_groups = find_cyclic_groups(dep_graph)

    report_progress("Done.")

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
        llm_szz_stats=llm_szz_stats,
    )
