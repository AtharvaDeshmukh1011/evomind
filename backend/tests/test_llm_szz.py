import json
import subprocess
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import pandas as pd
import pytest

from evomind.ingestion.git_miner import FileCommitRecord
from evomind.labeling.llm_szz import (
    AssessmentStats,
    InducingAssessment,
    LLMSZZError,
    assess_candidate,
    had_bug_before_cutoff_llm_assisted,
    refine_labels_with_llm_szz,
)


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _fake_client(payload: dict) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(content=[_text_block(json.dumps(payload))])
    return client


# --- assess_candidate (mocked LLM) ---


def test_assess_candidate_parses_plausible_true():
    client = _fake_client({"is_plausible_cause": True, "reason": "changes the same conditional the fix corrects"})
    result = assess_candidate("a.py", "fix diff", "candidate diff", "refactor", client=client)
    assert isinstance(result, InducingAssessment)
    assert result.is_plausible_cause is True


def test_assess_candidate_parses_plausible_false():
    client = _fake_client({"is_plausible_cause": False, "reason": "pure whitespace reformatting"})
    result = assess_candidate("a.py", "fix diff", "candidate diff", "style: reformat", client=client)
    assert result.is_plausible_cause is False


def test_assess_candidate_strips_markdown_fences():
    payload = {"is_plausible_cause": True, "reason": "ok"}
    client = MagicMock()
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    client.messages.create.return_value = SimpleNamespace(content=[_text_block(fenced)])
    result = assess_candidate("a.py", "f", "c", "m", client=client)
    assert result.is_plausible_cause is True


def test_assess_candidate_invalid_json_raises():
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(content=[_text_block("not json")])
    with pytest.raises(LLMSZZError, match="parse"):
        assess_candidate("a.py", "f", "c", "m", client=client)


def test_assess_candidate_auth_error_wrapped():
    client = MagicMock()
    client.messages.create.side_effect = anthropic.AuthenticationError(
        message="bad key", response=MagicMock(status_code=401, headers={}), body=None
    )
    with pytest.raises(LLMSZZError, match="ANTHROPIC_API_KEY"):
        assess_candidate("a.py", "f", "c", "m", client=client)


def test_assess_candidate_truncates_long_diffs():
    client = _fake_client({"is_plausible_cause": True, "reason": "ok"})
    huge_diff = "+x = 1\n" * 5000
    assess_candidate("a.py", huge_diff, huge_diff, "m", client=client)
    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    # Each diff block is capped at MAX_DIFF_CHARS -- the full 35000-char diff must not appear whole.
    assert len(prompt) < len(huge_diff)


# --- had_bug_before_cutoff_llm_assisted (real git repo + mocked LLM) ---


def _git(repo_dir, *args):
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo_dir, content, message, date):
    (repo_dir / "f.py").write_text(content)
    _git(repo_dir, "add", "f.py")
    _git(repo_dir, "commit", "-q", "-m", message, "--date", date.isoformat())
    return _git(repo_dir, "rev-parse", "HEAD")


@pytest.fixture
def bug_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-q", "-b", "master")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test")

    base = datetime(2023, 1, 1)
    _commit(repo_dir, "line1\nline2\nline3\n", "add f", base)
    bug_hash = _commit(repo_dir, "line1\nBUGGY\nline3\n", "introduce bug", base + timedelta(days=10))
    fix_hash = _commit(repo_dir, "line1\nFIXED\nline3\n", "fix: correct the bug", base + timedelta(days=20))

    return {"dir": repo_dir, "bug": bug_hash, "fix": fix_hash, "bug_date": base + timedelta(days=10)}


def test_llm_confirms_plausible_candidate_keeps_true(bug_repo):
    cutoff = bug_repo["bug_date"] + timedelta(days=5)
    client = _fake_client({"is_plausible_cause": True, "reason": "directly changes the buggy value"})
    result = had_bug_before_cutoff_llm_assisted(
        str(bug_repo["dir"]), "f.py", [bug_repo["fix"]], cutoff, client=client
    )
    assert result is True


def test_llm_rejects_false_positive_candidate(bug_repo):
    cutoff = bug_repo["bug_date"] + timedelta(days=5)
    client = _fake_client({"is_plausible_cause": False, "reason": "unrelated formatting change"})
    result = had_bug_before_cutoff_llm_assisted(
        str(bug_repo["dir"]), "f.py", [bug_repo["fix"]], cutoff, client=client
    )
    assert result is False


def test_date_filter_still_applies_before_any_llm_call(bug_repo):
    # Cutoff before the bug existed: candidate is disqualified by date alone,
    # so no LLM call should even be attempted.
    cutoff = bug_repo["bug_date"] - timedelta(days=5)
    client = MagicMock()
    result = had_bug_before_cutoff_llm_assisted(
        str(bug_repo["dir"]), "f.py", [bug_repo["fix"]], cutoff, client=client
    )
    assert result is False
    client.messages.create.assert_not_called()


def test_llm_failure_falls_back_to_plain_szz_behavior(bug_repo):
    cutoff = bug_repo["bug_date"] + timedelta(days=5)
    client = MagicMock()
    client.messages.create.side_effect = anthropic.AuthenticationError(
        message="bad key", response=MagicMock(status_code=401, headers={}), body=None
    )
    stats = AssessmentStats()
    result = had_bug_before_cutoff_llm_assisted(
        str(bug_repo["dir"]), "f.py", [bug_repo["fix"]], cutoff, client=client, stats=stats
    )
    assert result is True  # falls back to accepting, same as plain SZZ would
    assert stats.fallback == 1
    assert stats.assessed == 0


def test_stats_track_successful_assessment(bug_repo):
    cutoff = bug_repo["bug_date"] + timedelta(days=5)
    client = _fake_client({"is_plausible_cause": True, "reason": "ok"})
    stats = AssessmentStats()
    had_bug_before_cutoff_llm_assisted(
        str(bug_repo["dir"]), "f.py", [bug_repo["fix"]], cutoff, client=client, stats=stats
    )
    assert stats.assessed == 1
    assert stats.fallback == 0


# --- refine_labels_with_llm_szz (DataFrame-level orchestration) ---


def _rec(path, date, commit_hash="x", bug=False):
    return FileCommitRecord(
        file_path=path, commit_hash=commit_hash, author="a@example.com",
        author_date=date, lines_added=1, lines_removed=0, is_bug_fix=bug,
    )


def test_refine_keeps_label_when_llm_confirms(bug_repo):
    cutoff = bug_repo["bug_date"] + timedelta(days=5)
    horizon_end = cutoff + timedelta(days=30)
    train_df = pd.DataFrame([{"file_path": "f.py", "is_bug_prone": 1}])
    records = [_rec("f.py", cutoff + timedelta(days=1), bug_repo["fix"], bug=True)]
    client = _fake_client({"is_plausible_cause": True, "reason": "ok"})

    refined, stats = refine_labels_with_llm_szz(
        train_df, records, str(bug_repo["dir"]), cutoff, horizon_end, client=client
    )
    assert refined.loc[0, "is_bug_prone"] == 1
    assert stats.assessed == 1


def test_refine_drops_label_when_llm_rejects_as_false_positive(bug_repo):
    cutoff = bug_repo["bug_date"] + timedelta(days=5)
    horizon_end = cutoff + timedelta(days=30)
    train_df = pd.DataFrame([{"file_path": "f.py", "is_bug_prone": 1}])
    records = [_rec("f.py", cutoff + timedelta(days=1), bug_repo["fix"], bug=True)]
    client = _fake_client({"is_plausible_cause": False, "reason": "unrelated formatting change"})

    refined, stats = refine_labels_with_llm_szz(
        train_df, records, str(bug_repo["dir"]), cutoff, horizon_end, client=client
    )
    assert refined.loc[0, "is_bug_prone"] == 0
    assert stats.assessed == 1


def test_refine_leaves_negative_labels_untouched_and_skips_llm(bug_repo):
    cutoff = bug_repo["bug_date"] + timedelta(days=5)
    horizon_end = cutoff + timedelta(days=30)
    train_df = pd.DataFrame([{"file_path": "other.py", "is_bug_prone": 0}])
    client = MagicMock()

    refined, stats = refine_labels_with_llm_szz(
        train_df, [], str(bug_repo["dir"]), cutoff, horizon_end, client=client
    )
    assert refined.loc[0, "is_bug_prone"] == 0
    assert stats.assessed == 0
    client.messages.create.assert_not_called()
