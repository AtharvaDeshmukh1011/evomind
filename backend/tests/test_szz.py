import subprocess
from datetime import datetime, timedelta

import pandas as pd
import pytest

from evomind.ingestion.git_miner import FileCommitRecord
from evomind.labeling.szz import (
    had_bug_before_cutoff,
    refine_labels_with_szz,
    trace_inducing_commits,
)


def _git(repo_dir, *args):
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo_dir, content, message, date=None):
    (repo_dir / "f.py").write_text(content)
    _git(repo_dir, "add", "f.py")
    env_args = []
    if date:
        env_args = ["--date", date.isoformat()]
    _git(repo_dir, "commit", "-q", "-m", message, *env_args)
    return _git(repo_dir, "rev-parse", "HEAD")


@pytest.fixture
def bug_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-q", "-b", "master")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test")

    base = datetime(2023, 1, 1)
    add_hash = _commit(repo_dir, "line1\nline2\nline3\n", "add f", date=base)
    bug_hash = _commit(repo_dir, "line1\nBUGGY\nline3\n", "introduce bug", date=base + timedelta(days=10))
    fix_hash = _commit(repo_dir, "line1\nFIXED\nline3\n", "fix: correct the bug", date=base + timedelta(days=20))

    return {
        "dir": repo_dir,
        "add": add_hash,
        "bug": bug_hash,
        "fix": fix_hash,
        "bug_date": base + timedelta(days=10),
    }


def test_traces_fix_back_to_inducing_commit(bug_repo):
    results = trace_inducing_commits(str(bug_repo["dir"]), bug_repo["fix"], "f.py")
    assert len(results) == 1
    assert results[0].commit_hash == bug_repo["bug"]


def test_had_bug_before_cutoff_true_when_inducing_commit_predates_cutoff(bug_repo):
    cutoff = bug_repo["bug_date"] + timedelta(days=5)  # after the bug was introduced
    assert had_bug_before_cutoff(
        str(bug_repo["dir"]), "f.py", [bug_repo["fix"]], cutoff
    ) is True


def test_had_bug_before_cutoff_false_when_defect_introduced_after_cutoff(bug_repo):
    cutoff = bug_repo["bug_date"] - timedelta(days=5)  # before the bug existed
    assert had_bug_before_cutoff(
        str(bug_repo["dir"]), "f.py", [bug_repo["fix"]], cutoff
    ) is False


def test_root_commit_fix_traces_to_nothing(bug_repo):
    # The very first commit has no parent — nothing to blame.
    results = trace_inducing_commits(str(bug_repo["dir"]), bug_repo["add"], "f.py")
    assert results == []


def test_merge_commit_fix_traces_to_nothing(bug_repo):
    repo_dir = bug_repo["dir"]
    _git(repo_dir, "checkout", "-q", "-b", "feature", bug_repo["bug"])
    (repo_dir / "other.py").write_text("x = 1\n")
    _git(repo_dir, "add", "other.py")
    _git(repo_dir, "commit", "-q", "-m", "unrelated change on branch")
    _git(repo_dir, "checkout", "-q", "master")
    _git(repo_dir, "merge", "-q", "--no-ff", "feature", "-m", "merge feature")
    merge_hash = _git(repo_dir, "rev-parse", "HEAD")

    results = trace_inducing_commits(str(repo_dir), merge_hash, "f.py")
    assert results == []


def _rec(path, date, commit_hash="x", bug=False):
    return FileCommitRecord(
        file_path=path, commit_hash=commit_hash, author="a@example.com",
        author_date=date, lines_added=1, lines_removed=0, is_bug_fix=bug,
    )


def test_refine_keeps_label_when_defect_predates_cutoff(bug_repo):
    cutoff = bug_repo["bug_date"] + timedelta(days=5)
    horizon_end = cutoff + timedelta(days=30)
    train_df = pd.DataFrame([{"file_path": "f.py", "is_bug_prone": 1}])
    records = [_rec("f.py", cutoff + timedelta(days=1), bug_repo["fix"], bug=True)]

    refined = refine_labels_with_szz(train_df, records, str(bug_repo["dir"]), cutoff, horizon_end)
    assert refined.loc[0, "is_bug_prone"] == 1


def test_refine_drops_label_when_defect_introduced_after_cutoff(bug_repo):
    cutoff = bug_repo["bug_date"] - timedelta(days=5)  # before the bug existed
    horizon_end = cutoff + timedelta(days=30)
    train_df = pd.DataFrame([{"file_path": "f.py", "is_bug_prone": 1}])
    records = [_rec("f.py", cutoff + timedelta(days=1), bug_repo["fix"], bug=True)]

    refined = refine_labels_with_szz(train_df, records, str(bug_repo["dir"]), cutoff, horizon_end)
    assert refined.loc[0, "is_bug_prone"] == 0


def test_refine_leaves_negative_labels_untouched(bug_repo):
    cutoff = bug_repo["bug_date"] + timedelta(days=5)
    horizon_end = cutoff + timedelta(days=30)
    train_df = pd.DataFrame([{"file_path": "other.py", "is_bug_prone": 0}])

    refined = refine_labels_with_szz(train_df, [], str(bug_repo["dir"]), cutoff, horizon_end)
    assert refined.loc[0, "is_bug_prone"] == 0
