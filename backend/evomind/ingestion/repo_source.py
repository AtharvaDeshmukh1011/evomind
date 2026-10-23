from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager

_URL_PREFIXES = ("http://", "https://", "git@", "ssh://")

_NO_PROMPT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}

_CLONE_TIMEOUT_SECONDS = 900

_AUTH_FAILURE_MARKERS = (
    "could not read username",
    "could not read password",
    "authentication failed",
    "permission denied (publickey)",
    "terminal prompts disabled",
    "fatal: could not read from remote repository",
)

_NOT_FOUND_MARKERS = ("not found", "does not exist")


def is_remote(repo: str) -> bool:
    return repo.startswith(_URL_PREFIXES)


@contextmanager
def local_repo_path(repo: str):
    if not is_remote(repo):
        yield repo
        return

    tmp_dir = tempfile.mkdtemp(prefix="evomind_repo_")
    try:
        try:
            subprocess.run(
                ["git", "clone", "--quiet", "--single-branch", "--no-tags", repo, tmp_dir],
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
                f"Cloning '{repo}' did not finish within {_CLONE_TIMEOUT_SECONDS // 60} minutes. "
                "The repository is probably very large or the connection is slow; try again "
                "on a faster connection, or try a smaller repository."
            ) from exc
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
