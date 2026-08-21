"""SZZ-style bug-inducing commit tracing (Śliwerski, Zimmermann, Zeller, 2005).

The naive heuristic elsewhere in this project ("a bug-fixing commit touched
this file within the horizon") has a subtle leakage-adjacent flaw: it counts
a defect as "predictable at cutoff" even if the defect was actually
introduced *after* the cutoff — something no cutoff-time model could ever
see evidence of. SZZ fixes this by tracing each fix back to the commit that
last changed the lines it corrects (via `git blame` on the fix's parent
revision), so a file is only kept as bug-prone-at-cutoff when the underlying
defect genuinely already existed at that point in time.

Scope, deliberately: this traces line-level blame to find *when* a defect
was introduced, and keeps the existing file-level label only if that's
before cutoff. It does not relabel a *different* file than the one the fix
touched — in the large majority of real fixes the inducing change lives in
the same file anyway, so the value here is temporal correctness of the
label, not a different target file.

Known SZZ limitations shared with the literature: doesn't special-case
pure formatting/whitespace changes, cosmetic-only "fixes", or refactoring
commits that happen to match the bug-fix keyword heuristic — same class of
imprecision as the keyword heuristic itself, just one level deeper.
"""

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
    # Explicit utf-8 rather than text=True: git output is UTF-8 regardless
    # of platform, but text=True decodes using the OS default encoding —
    # cp1252 on Windows — which raises UnicodeDecodeError on any non-ASCII
    # byte in a commit's content (a real crash observed on real repos).
    # errors="replace" keeps this a best-effort trace, never a hard failure,
    # consistent with the rest of this module degrading gracefully rather
    # than raising when a commit can't be traced.
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
    """The commit's sole parent, or None for a merge or root commit.

    SZZ is ambiguous for merge commits (diff against which parent?) and
    undefined for root commits (nothing to blame) — both are skipped, a
    standard simplification in SZZ implementations.
    """
    out = _run_git(repo_path, "rev-list", "--parents", "-n", "1", commit_hash).split()
    return out[1] if len(out) == 2 else None


def _deleted_line_numbers(repo_path: str, parent: str, commit_hash: str, file_path: str) -> list[int]:
    """Line numbers, in `parent`'s version of the file, that `commit_hash` deletes or changes."""
    diff = _run_git(repo_path, "diff", "-U0", parent, commit_hash, "--", file_path)

    lines: list[int] = []
    for line in diff.splitlines():
        match = _HUNK_HEADER_RE.match(line)
        if not match:
            continue
        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) is not None else 1
        if old_count == 0:
            continue  # pure addition — nothing deleted to blame
        lines.extend(range(old_start, old_start + old_count))
    return lines


def _blame_commits_at_lines(
    repo_path: str, revision: str, file_path: str, line_numbers: set[int]
) -> set[str]:
    """The commit hash last touching each of `line_numbers` as of `revision`."""
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


@dataclass
class InducingCommit:
    commit_hash: str
    author_date: datetime


def trace_inducing_commits(
    repo_path: str, fix_commit_hash: str, file_path: str
) -> list[InducingCommit]:
    """Traces one fix commit's change to `file_path` back to the commit(s)
    that last touched the lines it corrects — the SZZ-identified
    bug-inducing commits. Returns an empty list for a merge/root fix commit,
    a newly-added file (nothing to blame), or a fix that couldn't be traced.
    """
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
    """True if any of `candidate_fix_commits` (bug-fixing commits touching
    `file_path`, already known to fall within the labeling horizon) traces
    back to an inducing commit at or before `cutoff` — i.e. the defect
    genuinely existed at prediction time, not just "some fix happened to
    land in this file later for unrelated reasons introduced afterward."
    """
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
    """Re-checks every file currently labeled `is_bug_prone=1` and keeps the
    label only if SZZ tracing confirms the underlying defect existed at or
    before `cutoff` — i.e. genuinely predictable from cutoff-time
    information, not a bug introduced later that a fix just happened to
    touch this file for within the horizon window.

    Only traces files that are currently positive (bounded, targeted cost —
    not every fix commit in the repo's history).
    """
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
