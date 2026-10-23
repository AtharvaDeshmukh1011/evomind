from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from evomind.ingestion.git_miner import FileCommitRecord, MinedRepository
from evomind.pipeline import run_pipeline


def _rec(path):
    return FileCommitRecord(
        file_path=path,
        commit_hash="abc123",
        author="dev@example.com",
        author_date=datetime(2024, 1, 1),
        lines_added=1,
        lines_removed=0,
        is_bug_fix=False,
    )


def _run_with(feature_table, records, use_llm_szz=False):
    with (
        patch("evomind.pipeline.local_repo_path") as repo,
        patch("evomind.pipeline.commit_date_range",
              return_value=(datetime(2023, 1, 1), datetime(2025, 1, 1))),
        patch("evomind.pipeline.mine_repository",
              return_value=MinedRepository(records=records)),
        patch("evomind.pipeline.commit_at_or_before", return_value="deadbeef"),
        patch("evomind.pipeline.read_files_at_commit", return_value={"a.py": "x = 1\n"}),
        patch("evomind.pipeline.build_feature_table", return_value=feature_table),
    ):
        repo.return_value.__enter__.return_value = "/tmp/fake"
        return run_pipeline("https://github.com/foss42/apidash", use_llm_szz=use_llm_szz)


def test_empty_feature_table_explains_itself_instead_of_raising_keyerror():
    with pytest.raises(ValueError) as exc:
        _run_with(pd.DataFrame([]), [_rec("lib/main.ex"), _rec("android/app.kt")])

    message = str(exc.value)
    assert "is_bug_prone" not in message
    assert "No analysable files remain" in message
    assert "Elixir" in message


def test_empty_table_message_reports_the_extensions_that_were_mined():
    with pytest.raises(ValueError) as exc:
        _run_with(pd.DataFrame([]), [_rec("android/app.kt"), _rec("ios/Runner.swift")])

    message = str(exc.value)
    assert ".kt" in message and ".swift" in message
    assert "2 change records" in message


def test_too_few_files_still_reports_counts_without_crashing():
    df = pd.DataFrame([{"file_path": f"f{i}.py", "is_bug_prone": 0} for i in range(5)])
    with pytest.raises(ValueError) as exc:
        _run_with(df, [_rec("f0.py")])

    message = str(exc.value)
    assert "only 5 source files" in message and "at least 20" in message


def test_single_label_class_is_rejected_with_both_counts():
    df = pd.DataFrame([{"file_path": f"f{i}.py", "is_bug_prone": 0} for i in range(30)])
    with pytest.raises(ValueError) as exc:
        _run_with(df, [_rec("f0.py")])

    assert "None of the 30 files needed a bug fix" in str(exc.value)


def test_empty_table_survives_the_llm_szz_path_too():
    with pytest.raises(ValueError) as exc:
        _run_with(pd.DataFrame([]), [_rec("lib/main.ex")], use_llm_szz=True)

    assert "No analysable files remain" in str(exc.value)
    assert "is_bug_prone" not in str(exc.value)


def test_refiners_return_an_empty_table_unchanged():
    from evomind.labeling.szz import refine_labels_with_szz
    from evomind.labeling.llm_szz import refine_labels_with_llm_szz

    empty = pd.DataFrame([])
    cutoff, horizon = datetime(2024, 1, 1), datetime(2025, 1, 1)

    assert refine_labels_with_szz(empty, [], "/tmp/x", cutoff, horizon).empty
    df, stats = refine_labels_with_llm_szz(empty, [], "/tmp/x", cutoff, horizon)
    assert df.empty and stats.assessed == 0 and stats.fallback == 0
