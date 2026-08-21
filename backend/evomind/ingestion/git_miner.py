"""Mines commit and file-change history from a Git repository using PyDriller."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from pydriller import Repository
from pydriller.domain.commit import ModificationType

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
    # Latest known source content per file, as of `snapshot_asof` (if given).
    snapshots: dict[str, str] = field(default_factory=dict)
    # Latest known source content per file as of the end of the mined range,
    # for scoring the repo's current state rather than a historical cutoff.
    latest_snapshots: dict[str, str] = field(default_factory=dict)


def is_bug_fixing_commit(message: str) -> bool:
    return bool(BUG_KEYWORDS.search(message or ""))


def mine_repository(
    repo_path_or_url: str,
    since: datetime | None = None,
    to: datetime | None = None,
    only_source_exts: tuple[str, ...] = (".py",),
    snapshot_asof: datetime | None = None,
    track_latest_snapshot: bool = False,
) -> MinedRepository:
    """Walks commit history and records per-file change events.

    `repo_path_or_url` may be a local path or a remote Git URL; PyDriller
    clones remote repos to a temp directory automatically.

    If `snapshot_asof` is given, also tracks the last-seen file content at or
    before that date, so features and labels can be split without leaking
    future information into the training snapshot. If `track_latest_snapshot`
    is set, content as of the end of the mined range is tracked too, for
    scoring the repo's current state.
    """
    mined = MinedRepository()

    for commit in Repository(repo_path_or_url, since=since, to=to).traverse_commits():
        bug_fix = is_bug_fixing_commit(commit.msg)
        author_date = commit.author_date.replace(tzinfo=None)
        take_snapshot = snapshot_asof is not None and author_date <= snapshot_asof

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

            deleted = mod.change_type == ModificationType.DELETE
            renamed_from = mod.old_path if mod.old_path and mod.old_path != path else None

            if take_snapshot:
                if deleted:
                    mined.snapshots.pop(path, None)
                else:
                    if renamed_from:
                        mined.snapshots.pop(renamed_from, None)
                    if mod.source_code is not None:
                        mined.snapshots[path] = mod.source_code

            if track_latest_snapshot:
                if deleted:
                    mined.latest_snapshots.pop(path, None)
                else:
                    if renamed_from:
                        mined.latest_snapshots.pop(renamed_from, None)
                    if mod.source_code is not None:
                        mined.latest_snapshots[path] = mod.source_code

    return mined
