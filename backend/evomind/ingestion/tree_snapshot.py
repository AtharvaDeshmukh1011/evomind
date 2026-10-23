from __future__ import annotations

import io
import os
import subprocess
import tarfile
from datetime import datetime

from evomind.ingestion.git_miner import parse_git_date
from evomind.metrics.code_metrics import SUPPORTED_EXTENSIONS


MAX_COMMITS = 20_000
MAX_SOURCE_BYTES = 500_000


def commit_date_range(repo_path: str, max_commits: int = MAX_COMMITS) -> tuple[datetime, datetime]:
    out = subprocess.run(
        ["git", "-C", repo_path, "log", "--format=%aI|%at", "-n", str(max_commits)],
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    dates = [parse_git_date(*line.split("|", 1)) for line in out.splitlines() if "|" in line]
    if not dates:
        raise ValueError("No commits found in repository.")
    return min(dates), max(dates)


def commit_at_or_before(repo_path: str, cutoff: datetime, ref: str = "HEAD") -> str | None:
    out = subprocess.run(
        ["git", "-C", repo_path, "rev-list", "-1", f"--before={cutoff.isoformat()}", ref],
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()
    return out or None


def read_files_at_commit(
    repo_path: str,
    commit_hash: str,
    only_source_exts: tuple[str, ...] = SUPPORTED_EXTENSIONS,
) -> dict[str, str]:
    proc = subprocess.run(
        ["git", "-C", repo_path, "archive", commit_hash],
        check=True,
        capture_output=True,
    )

    result: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            if only_source_exts and not member.name.endswith(only_source_exts):
                continue
            if member.size > MAX_SOURCE_BYTES:
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            path = member.name.replace("/", os.sep)
            content = extracted.read().decode("utf-8", errors="replace").replace("\r\n", "\n")
            result[path] = content

    return result
