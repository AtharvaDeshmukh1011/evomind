import subprocess
from unittest.mock import patch

import pytest

from evomind.ingestion.repo_source import is_remote, local_repo_path


def test_is_remote_recognizes_url_prefixes():
    assert is_remote("https://github.com/pallets/flask")
    assert is_remote("http://example.com/repo.git")
    assert is_remote("git@github.com:pallets/flask.git")
    assert is_remote("ssh://git@example.com/repo.git")


def test_is_remote_false_for_local_path():
    assert not is_remote("C:/Users/me/repo")
    assert not is_remote("/home/me/repo")


def test_local_repo_path_yields_local_path_unchanged(tmp_path):
    with local_repo_path(str(tmp_path)) as path:
        assert path == str(tmp_path)


def _clone_error(stderr: str) -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(returncode=128, cmd=["git", "clone"], output="", stderr=stderr)


def test_private_repo_without_credentials_raises_clear_error():
    error = _clone_error("fatal: could not read Username for 'https://github.com': terminal prompts disabled\n")
    with patch("subprocess.run", side_effect=error):
        with pytest.raises(ValueError, match="private repository"):
            with local_repo_path("https://github.com/someorg/private-repo.git"):
                pass


def test_ssh_auth_failure_raises_clear_error():
    error = _clone_error("git@github.com: Permission denied (publickey).\n")
    with patch("subprocess.run", side_effect=error):
        with pytest.raises(ValueError, match="private repository"):
            with local_repo_path("git@github.com:someorg/private-repo.git"):
                pass


def test_not_found_repo_mentions_both_possibilities_not_a_hard_claim():
    # GitHub (and most hosts) return "not found" for a private repo you can't
    # see, rather than "access denied" -- so this is genuinely ambiguous
    # between a typo'd URL and a real private repo, and the message should
    # say so rather than confidently asserting either one.
    error = _clone_error("remote: Repository not found.\nfatal: repository 'https://github.com/x/y.git/' not found\n")
    with patch("subprocess.run", side_effect=error):
        with pytest.raises(ValueError, match="Could not find") as exc_info:
            with local_repo_path("https://github.com/x/y.git"):
                pass
    assert "private repository" in str(exc_info.value)


def test_unrelated_clone_failure_gets_generic_message():
    error = _clone_error("fatal: unable to access 'https://github.com/x/y.git/': Could not resolve host: github.com\n")
    with patch("subprocess.run", side_effect=error):
        with pytest.raises(ValueError, match="Could not clone") as exc_info:
            with local_repo_path("https://github.com/x/y.git"):
                pass
    assert "private repository" not in str(exc_info.value)


def test_clone_timeout_raises_clear_error_instead_of_hanging():
    timeout_error = subprocess.TimeoutExpired(cmd=["git", "clone"], timeout=120)
    with patch("subprocess.run", side_effect=timeout_error):
        with pytest.raises(ValueError, match="did not finish within"):
            with local_repo_path("https://github.com/x/y.git"):
                pass


def test_clone_passes_no_prompt_env_vars():
    captured = {}

    def fake_run(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        raise subprocess.CalledProcessError(returncode=1, cmd=args[0], output="", stderr="boom")

    with patch("subprocess.run", side_effect=fake_run):
        with pytest.raises(ValueError):
            with local_repo_path("https://github.com/x/y.git"):
                pass

    assert captured["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert captured["env"]["GCM_INTERACTIVE"] == "never"
