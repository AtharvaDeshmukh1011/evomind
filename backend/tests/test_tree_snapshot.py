import subprocess
from datetime import datetime, timedelta

import pytest

from evomind.ingestion.tree_snapshot import commit_at_or_before, read_files_at_commit


def _git(repo_dir, *args):
    subprocess.run(["git", "-C", str(repo_dir), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def small_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-q")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test")

    (repo_dir / "a.py").write_text("x = 1\n")
    _git(repo_dir, "add", "a.py")
    _git(repo_dir, "commit", "-q", "-m", "add a")

    (repo_dir / "b.py").write_text("y = 2\n")
    _git(repo_dir, "add", "b.py")
    _git(repo_dir, "commit", "-q", "-m", "add b")

    return repo_dir


def test_commit_at_or_before_resolves_correct_commit(small_repo):
    far_future = datetime.now() + timedelta(days=1)
    commit = commit_at_or_before(str(small_repo), far_future)
    assert commit is not None


def test_commit_at_or_before_returns_none_before_history_starts(small_repo):
    far_past = datetime(1990, 1, 1)
    assert commit_at_or_before(str(small_repo), far_past) is None


def test_read_files_at_commit_reads_head(small_repo):
    files = read_files_at_commit(str(small_repo), "HEAD")
    assert set(files) == {"a.py", "b.py"}
    assert files["a.py"] == "x = 1\n"
    assert files["b.py"] == "y = 2\n"


def test_read_files_at_commit_filters_by_extension(small_repo):
    (small_repo / "readme.md").write_text("hello")
    _git(small_repo, "add", "readme.md")
    _git(small_repo, "commit", "-q", "-m", "add readme")

    files = read_files_at_commit(str(small_repo), "HEAD", only_source_exts=(".py",))
    assert "readme.md" not in files
    assert "a.py" in files


def test_read_files_at_commit_reflects_historical_state_not_current(small_repo):
    # First commit only had a.py — b.py didn't exist yet.
    first_commit = subprocess.run(
        ["git", "-C", str(small_repo), "rev-list", "--max-parents=0", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    files = read_files_at_commit(str(small_repo), first_commit)
    assert set(files) == {"a.py"}
