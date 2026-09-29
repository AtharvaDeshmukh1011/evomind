from datetime import datetime

from evomind.features.feature_builder import build_feature_table
from evomind.ingestion.git_miner import FileCommitRecord, MinedRepository

SOURCE = "def f(x):\n    return x + 1\n"


def _rec(path, date, added=1, removed=0, bug=False):
    return FileCommitRecord(
        file_path=path,
        commit_hash="abc",
        author="dev@example.com",
        author_date=date,
        lines_added=added,
        lines_removed=removed,
        is_bug_fix=bug,
    )


def test_label_true_for_bug_fix_within_horizon():
    cutoff = datetime(2024, 1, 1)
    mined = MinedRepository(
        records=[
            _rec("a.py", datetime(2023, 6, 1)),
            _rec("a.py", datetime(2024, 2, 1), bug=True),
        ]
    )
    df = build_feature_table(mined, cutoff=cutoff, snapshots={"a.py": SOURCE}, horizon_days=90)
    assert df.loc[df.file_path == "a.py", "is_bug_prone"].item() == 1


def test_label_false_when_bug_fix_outside_horizon():
    cutoff = datetime(2024, 1, 1)
    mined = MinedRepository(
        records=[
            _rec("a.py", datetime(2023, 6, 1)),
            _rec("a.py", datetime(2024, 6, 1), bug=True),
        ]
    )
    df = build_feature_table(mined, cutoff=cutoff, snapshots={"a.py": SOURCE}, horizon_days=90)
    assert df.loc[df.file_path == "a.py", "is_bug_prone"].item() == 0


def test_pre_cutoff_bug_fix_does_not_leak_into_label():
    cutoff = datetime(2024, 1, 1)
    mined = MinedRepository(records=[_rec("a.py", datetime(2023, 6, 1), bug=True)])
    df = build_feature_table(mined, cutoff=cutoff, snapshots={"a.py": SOURCE}, horizon_days=90)
    row = df[df.file_path == "a.py"].iloc[0]
    assert row["is_bug_prone"] == 0
    assert row["num_prior_bug_fixes"] == 1
