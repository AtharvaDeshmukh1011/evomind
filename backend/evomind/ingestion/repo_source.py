"""Resolves a repo argument (local path or Git URL) to a single local clone.

PyDriller re-clones a remote URL to a fresh temp directory on every
`Repository(...)` call. The pipeline mines the same repo twice (once for the
date range, once for features), so cloning once and reusing the local path
avoids paying for the clone over the network twice.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from contextlib import contextmanager

_URL_PREFIXES = ("http://", "https://", "git@", "ssh://")


def is_remote(repo: str) -> bool:
    return repo.startswith(_URL_PREFIXES)


@contextmanager
def local_repo_path(repo: str):
    """Yields a local filesystem path for `repo`, cloning first if it's a URL."""
    if not is_remote(repo):
        yield repo
        return

    tmp_dir = tempfile.mkdtemp(prefix="evomind_repo_")
    try:
        subprocess.run(
            ["git", "clone", "--quiet", repo, tmp_dir],
            check=True,
            capture_output=True,
            text=True,
        )
        yield tmp_dir
    finally:
        # GitPython/PyDriller can leave file handles open on Windows, which
        # turns cleanup into a no-op PermissionError rather than a real
        # failure — safe to ignore.
        shutil.rmtree(tmp_dir, ignore_errors=True)
