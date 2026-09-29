from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from evomind.ingestion.git_miner import FileCommitRecord, MinedRepository
from evomind.metrics.code_metrics import compute_file_metrics


def build_feature_table(
    mined: MinedRepository,
    cutoff: datetime,
    snapshots: dict[str, str],
    horizon_days: int = 90,
) -> pd.DataFrame:
    horizon_end = cutoff + timedelta(days=horizon_days)

    history: dict[str, list[FileCommitRecord]] = {}
    future_bug_files: set[str] = set()

    for rec in mined.records:
        if rec.author_date <= cutoff:
            history.setdefault(rec.file_path, []).append(rec)
        elif cutoff < rec.author_date <= horizon_end and rec.is_bug_fix:
            future_bug_files.add(rec.file_path)

    rows = []
    for file_path, recs in history.items():
        source = snapshots.get(file_path)
        if source is None:
            continue

        code_metrics = compute_file_metrics(file_path, source)
        if code_metrics is None:
            continue

        recs_sorted = sorted(recs, key=lambda r: r.author_date)
        first_seen = recs_sorted[0].author_date
        last_seen = recs_sorted[-1].author_date

        num_commits = len(recs_sorted)
        num_authors = len({r.author for r in recs_sorted})
        total_added = sum(r.lines_added for r in recs_sorted)
        total_removed = sum(r.lines_removed for r in recs_sorted)
        churn = total_added + total_removed
        num_bug_fixes = sum(1 for r in recs_sorted if r.is_bug_fix)
        age_days = (cutoff - first_seen).days
        recency_days = (cutoff - last_seen).days

        rows.append(
            {
                "file_path": file_path,
                "num_commits": num_commits,
                "num_authors": num_authors,
                "lines_added_total": total_added,
                "lines_removed_total": total_removed,
                "churn": churn,
                "num_prior_bug_fixes": num_bug_fixes,
                "age_days": age_days,
                "recency_days": recency_days,
                "loc": code_metrics.loc,
                "sloc": code_metrics.sloc,
                "avg_cyclomatic_complexity": code_metrics.avg_cyclomatic_complexity,
                "max_cyclomatic_complexity": code_metrics.max_cyclomatic_complexity,
                "function_count": code_metrics.function_count,
                "maintainability_index": code_metrics.maintainability_index,
                "halstead_volume": code_metrics.halstead_volume,
                "halstead_difficulty": code_metrics.halstead_difficulty,
                "is_bug_prone": int(file_path in future_bug_files),
            }
        )

    return pd.DataFrame(rows)
