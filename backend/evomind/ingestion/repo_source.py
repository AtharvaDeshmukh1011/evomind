"""Resolves a repo argument (local path or Git URL) to a single local clone.

PyDriller re-clones a remote URL to a fresh temp directory on every
`Repository(...)` call. The pipeline mines the same repo twice (once for the
date range, once for features), so cloning once and reusing the local path
avoids paying for the clone over the network twice.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager

_URL_PREFIXES = ("http://", "https://", "git@", "ssh://")

# Without these, `git clone` on a private repo with no credentials configured
# doesn't fail — it hangs waiting for a prompt nobody can answer (a terminal
# username/password prompt, or a GUI credential-manager popup on Windows).
# GIT_TERMINAL_PROMPT=0 disables the former; GCM_INTERACTIVE=never disables
# the latter for Git Credential Manager specifically. Together, an
# unauthenticated private-repo clone fails in under a second with a clear
# stderr message instead of hanging the request indefinitely.
_NO_PROMPT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}

# Kept as a backstop, not the primary defense — the env vars above should
# make an auth failure fail fast on their own. This only matters if some
# other credential helper ignores both variables.
_CLONE_TIMEOUT_SECONDS = 120

_AUTH_FAILURE_MARKERS = (
    "could not read username",
    "could not read password",
    "authentication failed",
    "permission denied (publickey)",
    "terminal prompts disabled",
    "fatal: could not read from remote repository",
)

# GitHub (and others) deliberately return "not found" for a private repo you
# can't see, rather than "access denied" -- that would leak whether the repo
# exists at all to an unauthorized caller. So "not found" is genuinely
# ambiguous between "typo'd URL" and "private repo, no credentials" -- worth
# surfacing both possibilities rather than asserting either one.
_NOT_FOUND_MARKERS = ("not found", "does not exist")


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
        try:
            subprocess.run(
                ["git", "clone", "--quiet", repo, tmp_dir],
                check=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, **_NO_PROMPT_ENV},
                timeout=_CLONE_TIMEOUT_SECONDS,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").lower()
            if any(marker in stderr for marker in _AUTH_FAILURE_MARKERS):
                raise ValueError(
                    f"'{repo}' looks like a private repository — EvoMind has no "
                    "credentials configured to access it. Point it at a public "
                    "repo, or configure Git credentials on the server first."
                ) from exc
            if any(marker in stderr for marker in _NOT_FOUND_MARKERS):
                raise ValueError(
                    f"Could not find '{repo}'. Either the URL is wrong, or it's "
                    "a private repository — GitHub (and most hosts) show \"not "
                    "found\" rather than \"access denied\" for repos you can't "
                    "see, so this could be either. EvoMind has no credentials "
                    "configured, so a private repo won't work either way."
                ) from exc
            raise ValueError(f"Could not clone '{repo}': {exc.stderr or exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                f"Cloning '{repo}' did not finish within {_CLONE_TIMEOUT_SECONDS}s "
                "— check the URL, or that the repo doesn't require credentials "
                "EvoMind doesn't have."
            ) from exc
        yield tmp_dir
    finally:
        # GitPython/PyDriller can leave file handles open on Windows, which
        # turns cleanup into a no-op PermissionError rather than a real
        # failure — safe to ignore.
        shutil.rmtree(tmp_dir, ignore_errors=True)
