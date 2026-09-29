from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from pydriller import Repository

from evomind.metrics.code_metrics import SUPPORTED_EXTENSIONS

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
    only_source_exts: tuple[str, ...] = SUPPORTED_EXTENSIONS,
) -> MinedRepository:
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
