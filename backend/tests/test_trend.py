from __future__ import annotations

from datetime import datetime

import pandas as pd

from evomind.ingestion.git_miner import FileCommitRecord, MinedRepository
from evomind.ml.trend import (
    TREND_POINTS,
    TrendPoint,
    compute_risk_trends,
    trend_delta,
    trend_times,
)

SOURCE = "def f(x):\n    if x:\n        return 1\n    return 0\n"


class CommitCountModel:
    def predict_proba(self, X):
        risk = (X["num_commits"].to_numpy() / 10).clip(0, 1)
        return pd.DataFrame({0: 1 - risk, 1: risk}).to_numpy()


def _rec(path, when):
    return FileCommitRecord(
        file_path=path, commit_hash="h", author="dev@example.com", author_date=when,
        lines_added=1, lines_removed=0, is_bug_fix=False,
    )


def test_trend_times_are_increasing_and_end_before_now():
    start, end = datetime(2020, 1, 1), datetime(2025, 1, 1)
    times = trend_times(start, end)
    assert len(times) == TREND_POINTS - 1
    assert times == sorted(times)
    assert start < times[0] and times[-1] < end


def test_risk_rises_as_a_file_accumulates_commits():
    mined = MinedRepository(records=[_rec("a.py", datetime(2021, m, 1)) for m in range(1, 9)])
    history = [(datetime(2021, 2, 15), {"a.py": SOURCE}), (datetime(2021, 5, 15), {"a.py": SOURCE})]
    current = pd.DataFrame({"file_path": ["a.py"], "risk_score": [0.8]})

    trends = compute_risk_trends(CommitCountModel(), mined, history, datetime(2021, 12, 1), current)

    risks = [p.risk for p in trends["a.py"]]
    assert risks == [0.2, 0.5, 0.8]
    assert trend_delta(trends["a.py"]) == 0.8 - 0.2


def test_file_absent_from_an_earlier_snapshot_has_a_gap_not_a_zero():
    mined = MinedRepository(records=[_rec("a.py", datetime(2021, 1, 1)), _rec("b.py", datetime(2021, 6, 1))])
    history = [(datetime(2021, 3, 1), {"a.py": SOURCE})]
    current = pd.DataFrame({"file_path": ["a.py", "b.py"], "risk_score": [0.1, 0.3]})

    trends = compute_risk_trends(CommitCountModel(), mined, history, datetime(2021, 12, 1), current)

    assert trends["b.py"][0].risk is None
    assert trends["b.py"][-1].risk == 0.3


def test_last_point_is_exactly_the_current_score():
    mined = MinedRepository(records=[_rec("a.py", datetime(2021, 1, 1))])
    current = pd.DataFrame({"file_path": ["a.py"], "risk_score": [0.42]})
    trends = compute_risk_trends(CommitCountModel(), mined, [], datetime(2021, 12, 1), current)
    assert trends["a.py"] == [TrendPoint(date="2021-12-01", risk=0.42)]


def test_delta_needs_two_known_points():
    assert trend_delta([TrendPoint("2021-01-01", None), TrendPoint("2021-06-01", 0.4)]) is None
    assert trend_delta([TrendPoint("2021-01-01", 0.5), TrendPoint("2021-06-01", None),
                        TrendPoint("2021-12-01", 0.2)]) == 0.2 - 0.5
