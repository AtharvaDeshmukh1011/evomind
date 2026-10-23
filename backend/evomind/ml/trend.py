from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from evomind.features.feature_builder import build_feature_table
from evomind.ingestion.git_miner import MinedRepository
from evomind.ml.train import FEATURE_COLUMNS

TREND_POINTS = 6
TREND_START_FRACTION = 0.3


@dataclass
class TrendPoint:
    date: str
    risk: float | None


def trend_times(start: datetime, end: datetime, points: int = TREND_POINTS) -> list[datetime]:
    step = (1 - TREND_START_FRACTION) / (points - 1)
    return [start + (end - start) * (TREND_START_FRACTION + i * step) for i in range(points - 1)]


TREND_FILE_LIMIT = 300


def score_at(model, mined: MinedRepository, when: datetime, snapshots: dict[str, str]) -> dict[str, float]:
    frame = build_feature_table(mined, cutoff=when, snapshots=snapshots, horizon_days=0)
    if frame.empty:
        return {}
    return dict(zip(frame["file_path"], model.predict_proba(frame[FEATURE_COLUMNS])[:, 1]))


def compute_risk_trends(
    model,
    mined: MinedRepository,
    history: list[tuple[datetime, dict[str, str]]],
    now: datetime,
    current: pd.DataFrame,
    limit: int = TREND_FILE_LIMIT,
) -> dict[str, list[TrendPoint]]:
    focus = set(current.nlargest(limit, "risk_score")["file_path"]) if len(current) > limit else None
    series = [
        (when, score_at(model, mined, when, snapshots if focus is None else {p: src for p, src in snapshots.items() if p in focus}))
        for when, snapshots in history
    ]
    series.append((now, dict(zip(current["file_path"], current["risk_score"]))))
    return {
        path: [
            TrendPoint(date=when.date().isoformat(), risk=None if risk.get(path) is None else float(risk[path]))
            for when, risk in series
        ]
        for path in current["file_path"]
    }


def trend_delta(points: list[TrendPoint]) -> float | None:
    known = [p.risk for p in points if p.risk is not None]
    return known[-1] - known[0] if len(known) >= 2 else None
