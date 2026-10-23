from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

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


def parse_git_date(iso_text: str, unix_text: str) -> datetime:
    try:
        return datetime.fromisoformat(iso_text.strip()).replace(tzinfo=None)
    except ValueError:
        return datetime.fromtimestamp(int(unix_text.strip()), tz=timezone.utc).replace(tzinfo=None)


def is_bug_fixing_commit(message: str) -> bool:
    return bool(BUG_KEYWORDS.search(message or ""))


def mine_repository(
    repo_path_or_url: str,
    since: datetime | None = None,
    to: datetime | None = None,
    only_source_exts: tuple[str, ...] = SUPPORTED_EXTENSIONS,
) -> MinedRepository:
    if os.path.isdir(repo_path_or_url):
        return _mine_with_git_log(repo_path_or_url, since, to, only_source_exts)
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


RENAME_BRACES = re.compile(r"\{([^{}]*) => ([^{}]*)\}")


def _new_path(raw: str) -> str:
    if "{" in raw and " => " in raw:
        return RENAME_BRACES.sub(lambda m: m.group(2), raw).replace("//", "/")
    if " => " in raw:
        return raw.split(" => ", 1)[1]
    return raw


def _mine_with_git_log(
    repo_path: str,
    since: datetime | None,
    to: datetime | None,
    only_source_exts: tuple[str, ...],
) -> MinedRepository:
    cmd = ["git", "-C", repo_path, "-c", "core.quotepath=off", "log", "--reverse", "--no-merges", "-M",
           "--numstat", "--format=%x1e%H%x1f%ae%x1f%an%x1f%aI%x1f%at%x1f%B%x1f"]
    if since is not None:
        cmd.append(f"--since={since.isoformat()}")
    if to is not None:
        cmd.append(f"--until={to.isoformat()}")
    out = subprocess.run(cmd, check=True, capture_output=True, encoding="utf-8", errors="replace").stdout
    mined = MinedRepository()
    for chunk in out.split(""):
        if not chunk.strip():
            continue
        parts = chunk.split("")
        if len(parts) < 7:
            continue
        commit_hash, email, name, date_text, unix_text, message, stats = parts[:7]
        author_date = parse_git_date(date_text, unix_text)
        bug_fix = is_bug_fixing_commit(message)
        for line in stats.splitlines():
            fields = line.split("	")
            if len(fields) != 3:
                continue
            path = _new_path(fields[2]).replace("/", os.sep)
            if only_source_exts and not path.endswith(only_source_exts):
                continue
            mined.records.append(
                FileCommitRecord(
                    file_path=path,
                    commit_hash=commit_hash.strip(),
                    author=email or name or "unknown",
                    author_date=author_date,
                    lines_added=int(fields[0]) if fields[0].isdigit() else 0,
                    lines_removed=int(fields[1]) if fields[1].isdigit() else 0,
                    is_bug_fix=bug_fix,
                )
            )
    return mined

