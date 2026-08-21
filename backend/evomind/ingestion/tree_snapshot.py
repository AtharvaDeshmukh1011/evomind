"""Reads exact file trees from a local Git repo at a specific commit.

Reconstructing "the repo's state as of some point in time" by replaying
commit diffs chronologically (pop on delete, add on create, ...) is unsound
whenever history is non-linear: a long-lived branch created *before* a file
rename, merged *after* it, gets visited by a chronological traversal in
commit-date order — so a file already renamed away on the mainline gets
"resurrected" by that branch's later-dated (but logically earlier) commits.
This was observed for real on Flask's history (`flask/app.py` renamed to
`src/flask/app.py` in 2019, then reappearing from a pre-rename branch merged
weeks later).

`git rev-list` + `git archive` sidestep the whole problem: they resolve one
exact commit and read its tree directly, with no diff replay involved.
"""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
from datetime import datetime


def commit_at_or_before(repo_path: str, cutoff: datetime, ref: str = "HEAD") -> str | None:
    """The hash of the latest commit at or before `cutoff`, on `ref`'s ancestry."""
    out = subprocess.run(
        ["git", "-C", repo_path, "rev-list", "-1", f"--before={cutoff.isoformat()}", ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return out or None


def read_files_at_commit(
    repo_path: str,
    commit_hash: str,
    only_source_exts: tuple[str, ...] = (".py",),
) -> dict[str, str]:
    """Reads every matching file's exact content at `commit_hash`, via `git archive`.

    One subprocess call for the whole tree rather than one `git show` per
    file — both faster and immune to the replay bug described above.
    """
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
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            # tar entries always use "/", regardless of platform — normalize
            # to match the OS-native separators PyDriller returns elsewhere
            # (e.g. FileCommitRecord.file_path), so the two can be joined on.
            path = member.name.replace("/", os.sep)
            # Windows' core.autocrlf can make `git archive` emit CRLF even
            # though the repo stores LF — normalize so LOC counts and code
            # metrics don't vary by the host's git config.
            content = extracted.read().decode("utf-8", errors="replace").replace("\r\n", "\n")
            result[path] = content

    return result
