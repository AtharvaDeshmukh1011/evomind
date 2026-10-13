from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from evomind.ml.train import FEATURE_COLUMNS

FEATURE_LABELS = {
    "num_commits": "commits",
    "num_authors": "distinct authors",
    "lines_added_total": "lines added",
    "lines_removed_total": "lines removed",
    "churn": "churn",
    "num_prior_bug_fixes": "past bug fixes",
    "age_days": "age (days)",
    "recency_days": "days since last change",
    "loc": "lines of code",
    "sloc": "source lines",
    "avg_cyclomatic_complexity": "avg complexity",
    "max_cyclomatic_complexity": "max complexity",
    "function_count": "functions",
    "maintainability_index": "maintainability",
    "halstead_volume": "Halstead volume",
    "halstead_difficulty": "Halstead difficulty",
}


@dataclass
class Reason:
    feature: str
    label: str
    value: float
    percentile: float
    impact: float


def explain_risk(model, frame: pd.DataFrame, top_k: int = 3, min_impact: float = 0.005) -> list[list[Reason]]:
    if frame.empty:
        return []

    X = frame[FEATURE_COLUMNS]
    base = model.predict_proba(X)[:, 1]
    medians = X.median()
    percentiles = X.rank(pct=True)

    impacts = {}
    for col in FEATURE_COLUMNS:
        typical = X.copy()
        typical[col] = medians[col]
        impacts[col] = base - model.predict_proba(typical)[:, 1]

    explanations = []
    for i in range(len(X)):
        ranked = sorted(
            ((col, impacts[col][i]) for col in FEATURE_COLUMNS if impacts[col][i] >= min_impact),
            key=lambda kv: kv[1],
            reverse=True,
        )[:top_k]
        explanations.append([
            Reason(
                feature=col,
                label=FEATURE_LABELS[col],
                value=float(X.iloc[i][col]),
                percentile=float(percentiles.iloc[i][col]),
                impact=float(impact),
            )
            for col, impact in ranked
        ])
    return explanations
