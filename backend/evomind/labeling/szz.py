from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from evomind.ingestion.git_miner import FileCommitRecord

_BLAME_HEADER_RE = re.compile(r"^([0-9a-f]{40}) \d+ (\d+)")
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def _run_git(repo_path: str, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, *args],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""
    return result.stdout if result.returncode == 0 and result.stdout is not None else ""


def _single_parent(repo_path: str, commit_hash: str) -> str | None:
    out = _run_git(repo_path, "rev-list", "--parents", "-n", "1", commit_hash).split()
    return out[1] if len(out) == 2 else None


def _deleted_line_numbers(repo_path: str, parent: str, commit_hash: str, file_path: str) -> list[int]:
    diff = _run_git(repo_path, "diff", "-U0", parent, commit_hash, "--", file_path)

    lines: list[int] = []
    for line in diff.splitlines():
        match = _HUNK_HEADER_RE.match(line)
        if not match:
            continue
        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) is not None else 1
        if old_count == 0:
            continue
        lines.extend(range(old_start, old_start + old_count))
    return lines


def _blame_commits_at_lines(
    repo_path: str, revision: str, file_path: str, line_numbers: set[int]
) -> set[str]:
    if not line_numbers:
        return set()

    blame_out = _run_git(repo_path, "blame", revision, "--porcelain", "--", file_path)
    line_to_commit: dict[int, str] = {}
    for line in blame_out.splitlines():
        match = _BLAME_HEADER_RE.match(line)
        if match:
            line_to_commit[int(match.group(2))] = match.group(1)

    return {line_to_commit[n] for n in line_numbers if n in line_to_commit}


def _commit_author_date(repo_path: str, commit_hash: str) -> datetime | None:
    out = _run_git(repo_path, "show", "-s", "--format=%aI", commit_hash).strip()
    if not out:
        return None
    return datetime.fromisoformat(out).replace(tzinfo=None)


def commit_diff_text(repo_path: str, commit_hash: str, file_path: str, context_lines: int = 3) -> str:
    parent = _single_parent(repo_path, commit_hash)
    if parent is None:
        return ""
    return _run_git(repo_path, "diff", f"-U{context_lines}", parent, commit_hash, "--", file_path)


def commit_message(repo_path: str, commit_hash: str) -> str:
    return _run_git(repo_path, "show", "-s", "--format=%s", commit_hash).strip()


@dataclass
class InducingCommit:
    commit_hash: str
    author_date: datetime


def trace_inducing_commits(
    repo_path: str, fix_commit_hash: str, file_path: str
) -> list[InducingCommit]:
    parent = _single_parent(repo_path, fix_commit_hash)
    if parent is None:
        return []

    deleted_lines = set(_deleted_line_numbers(repo_path, parent, fix_commit_hash, file_path))
    if not deleted_lines:
        return []

    inducing_hashes = _blame_commits_at_lines(repo_path, parent, file_path, deleted_lines)

    results = []
    for h in inducing_hashes:
        date = _commit_author_date(repo_path, h)
        if date is not None:
            results.append(InducingCommit(commit_hash=h, author_date=date))
    return results


def had_bug_before_cutoff(
    repo_path: str,
    file_path: str,
    candidate_fix_commits: list[str],
    cutoff: datetime,
) -> bool:
    for fix_hash in candidate_fix_commits:
        for inducing in trace_inducing_commits(repo_path, fix_hash, file_path):
            if inducing.author_date <= cutoff:
                return True
    return False


def refine_labels_with_szz(
    train_df: pd.DataFrame,
    mined_records: list[FileCommitRecord],
    repo_path: str,
    cutoff: datetime,
    horizon_end: datetime,
) -> pd.DataFrame:
    if train_df.empty:
        return train_df

    positive_files = set(train_df.loc[train_df["is_bug_prone"] == 1, "file_path"])
    if not positive_files:
        return train_df

    fixes_by_file: dict[str, list[str]] = {}
    for rec in mined_records:
        if rec.file_path in positive_files and rec.is_bug_fix and cutoff < rec.author_date <= horizon_end:
            fixes_by_file.setdefault(rec.file_path, []).append(rec.commit_hash)

    confirmed = {
        file_path
        for file_path, fix_hashes in fixes_by_file.items()
        if had_bug_before_cutoff(repo_path, file_path, fix_hashes, cutoff)
    }

    refined = train_df.copy()
    still_positive = refined["is_bug_prone"] == 1
    refined.loc[still_positive, "is_bug_prone"] = (
        refined.loc[still_positive, "file_path"].isin(confirmed).astype(int)
    )
    return refined
