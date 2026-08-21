"""Mines commit history from a Git repository using PyDriller.

File *content* snapshots (both "as of a cutoff date" and "current") are
deliberately not produced here — see `evomind/ingestion/tree_snapshot.py`
for why replaying commit diffs chronologically to reconstruct a point-in-time
tree is unsound for non-linear history, and how it's done correctly instead.
This module only extracts the process-metric inputs: who changed what file,
when, by how much, and whether the commit looks like a bug fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from pydriller import Repository

# Keyword heuristic for identifying bug-fixing commits, following the
# widely used approach from Kim et al. and later defect-prediction studies
# (e.g. the SZZ-style labeling referenced in Malhotra & Khanna, 2022).
BUG_KEYWORDS = re.compile(
    r"\b(fix(e[sd])?|bug|defect|error|crash|fault|patch|issue|regression|"
    r"broken|fail(s|ed|ure)?|npe|exception)\b",
    re.IGNORECASE,
)


@dataclass
class FileCommitRecord:
    file_path: str
    commit_hash: str
    author: str
    author_date: datetime
    lines_added: int
    lines_removed: int
    is_bug_fix: bool


@dataclass
class MinedRepository:
    records: list[FileCommitRecord] = field(default_factory=list)


def is_bug_fixing_commit(message: str) -> bool:
    return bool(BUG_KEYWORDS.search(message or ""))


def mine_repository(
    repo_path_or_url: str,
    since: datetime | None = None,
    to: datetime | None = None,
    only_source_exts: tuple[str, ...] = (".py",),
) -> MinedRepository:
    """Walks commit history and records per-file change events.

    `repo_path_or_url` may be a local path or a remote Git URL; PyDriller
    clones remote repos to a temp directory automatically.
    """
    mined = MinedRepository()

    for commit in Repository(repo_path_or_url, since=since, to=to).traverse_commits():
        bug_fix = is_bug_fixing_commit(commit.msg)
        author_date = commit.author_date.replace(tzinfo=None)

        for mod in commit.modified_files:
            path = mod.new_path or mod.old_path
            if path is None:
                continue
            if only_source_exts and not path.endswith(only_source_exts):
                continue

            mined.records.append(
                FileCommitRecord(
                    file_path=path,
                    commit_hash=commit.hash,
                    author=commit.author.email or commit.author.name or "unknown",
                    author_date=author_date,
                    lines_added=mod.added_lines or 0,
                    lines_removed=mod.deleted_lines or 0,
                    is_bug_fix=bug_fix,
                )
            )

    return mined
