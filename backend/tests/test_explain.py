from __future__ import annotations

import numpy as np
import pandas as pd

from evomind.ml.explain import FEATURE_LABELS, explain_risk
from evomind.ml.train import FEATURE_COLUMNS, LABEL_COLUMN, train_and_evaluate


def _churn_driven_table(n=300, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(rng.normal(size=(n, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    df[LABEL_COLUMN] = (df["churn"] + rng.normal(scale=0.3, size=n) > 0.8).astype(int)
    return df


def test_every_feature_has_a_label():
    assert set(FEATURE_LABELS) == set(FEATURE_COLUMNS)


def test_one_explanation_per_file():
    df = _churn_driven_table()
    report = train_and_evaluate(df)
    assert len(explain_risk(report.model, df)) == len(df)


def test_dominant_feature_is_named_for_the_riskiest_files():
    df = _churn_driven_table()
    report = train_and_evaluate(df)
    reasons = explain_risk(report.model, df)
    risk = report.model.predict_proba(df[FEATURE_COLUMNS])[:, 1]
    top = np.argsort(risk)[-10:]
    assert sum(reasons[i] and reasons[i][0].feature == "churn" for i in top) >= 8


def test_reasons_are_sorted_capped_and_positive():
    df = _churn_driven_table()
    report = train_and_evaluate(df)
    for row in explain_risk(report.model, df, top_k=3):
        assert len(row) <= 3
        impacts = [r.impact for r in row]
        assert impacts == sorted(impacts, reverse=True)
        assert all(i > 0 for i in impacts)


def test_stated_impact_is_what_actually_happens():
    df = _churn_driven_table()
    report = train_and_evaluate(df)
    reasons = explain_risk(report.model, df)
    i = int(np.argmax(report.model.predict_proba(df[FEATURE_COLUMNS])[:, 1]))
    r = reasons[i][0]
    before = report.model.predict_proba(df[FEATURE_COLUMNS].iloc[[i]])[0, 1]
    typical = df[FEATURE_COLUMNS].iloc[[i]].copy()
    typical[r.feature] = df[r.feature].median()
    after = report.model.predict_proba(typical)[0, 1]
    assert abs((before - after) - r.impact) < 1e-9


def test_percentile_reflects_rank_in_the_repo():
    df = _churn_driven_table()
    report = train_and_evaluate(df)
    reasons = explain_risk(report.model, df)
    i = int(df["churn"].idxmax())
    churn = [r for r in reasons[i] if r.feature == "churn"]
    if churn:
        assert churn[0].percentile == 1.0


def test_constant_feature_never_appears_as_a_reason():
    df = _churn_driven_table()
    df["maintainability_index"] = 0.0
    report = train_and_evaluate(df)
    for row in explain_risk(report.model, df):
        assert all(r.feature != "maintainability_index" for r in row)


def test_empty_frame_gives_no_explanations():
    df = _churn_driven_table()
    report = train_and_evaluate(df)
    assert explain_risk(report.model, df.iloc[0:0]) == []
