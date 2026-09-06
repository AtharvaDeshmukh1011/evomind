"""Model selection tests.

The central invariant here: whichever model `best_model_name` reports is the
model `report.model` actually holds — because `report.model` is what scores
every file in `evomind/pipeline.py`. An earlier version hardcoded the forest
as the scorer while still reporting a winner by metric, so the dashboard
could announce "best model: logistic regression" over a risk ranking the
forest produced. `test_selected_model_is_the_reported_best_model` covers
that regression directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline

from evomind.ml.train import (
    FEATURE_COLUMNS,
    LABEL_COLUMN,
    EvalResult,
    _selection_key,
    train_and_evaluate,
)


def _linear_table(n: int, noise: float, seed: int) -> pd.DataFrame:
    """Purely linear signal spread across every feature. With a small `n`
    the forest overfits and the linear baseline wins; with a large `n` the
    forest catches up. Lets both selection branches be exercised."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, len(FEATURE_COLUMNS)))
    score = X @ np.linspace(1, 3, len(FEATURE_COLUMNS)) + rng.normal(scale=noise, size=n)
    df = pd.DataFrame(X, columns=FEATURE_COLUMNS)
    df[LABEL_COLUMN] = (score > np.median(score)).astype(int)
    return df


def _interaction_table(n: int, seed: int) -> pd.DataFrame:
    """XOR-style interaction no linear model can separate — the forest wins."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, len(FEATURE_COLUMNS)))
    score = ((X[:, 0] > 0) ^ (X[:, 1] > 0)).astype(float) * 5 + rng.normal(scale=0.3, size=n)
    df = pd.DataFrame(X, columns=FEATURE_COLUMNS)
    df[LABEL_COLUMN] = (score > np.median(score)).astype(int)
    return df


def _resolve(model) -> str:
    return "logistic_regression_baseline" if isinstance(model, Pipeline) else "random_forest"


@pytest.mark.parametrize(
    "df,expected_winner",
    [
        (_linear_table(n=70, noise=0.5, seed=3), "logistic_regression_baseline"),
        (_interaction_table(n=400, seed=7), "random_forest"),
    ],
    ids=["logistic_wins", "forest_wins"],
)
def test_selected_model_is_the_reported_best_model(df, expected_winner):
    """`report.model` must be the model `best_model_name` names — for both
    possible winners, not just the forest."""
    report = train_and_evaluate(df)

    assert report.best_model_name == expected_winner
    assert _resolve(report.model) == report.best_model_name


def test_selected_model_is_fitted_and_scores_probabilities():
    """Whichever model is selected has to be usable exactly the way
    pipeline.py uses it: `predict_proba(...)[:, 1]` over FEATURE_COLUMNS."""
    df = _linear_table(n=70, noise=0.5, seed=3)
    report = train_and_evaluate(df)

    scores = report.model.predict_proba(df[FEATURE_COLUMNS])[:, 1]

    assert len(scores) == len(df)
    assert ((scores >= 0) & (scores <= 1)).all()


@pytest.mark.parametrize(
    "df,expected_kind",
    [
        (_linear_table(n=70, noise=0.5, seed=3), "absolute standardized coefficient"),
        (_interaction_table(n=400, seed=7), "mean decrease in impurity"),
    ],
    ids=["logistic_coefficients", "forest_impurity"],
)
def test_feature_importances_describe_the_selected_model(df, expected_kind):
    """Importances must come from the model that produced the scores, and
    say which quantity they are — the forest's impurity decrease and the
    logistic model's standardized coefficients are not the same thing."""
    report = train_and_evaluate(df)

    assert expected_kind in report.feature_importance_kind
    assert set(report.feature_importances) == set(FEATURE_COLUMNS)
    # Normalized so both kinds render against the same axis in the dashboard.
    assert sum(report.feature_importances.values()) == pytest.approx(1.0)


def test_feature_importances_are_ranked_descending():
    report = train_and_evaluate(_interaction_table(n=400, seed=7))
    values = list(report.feature_importances.values())
    assert values == sorted(values, reverse=True)


def test_saved_model_is_the_selected_one(tmp_path):
    """The joblib artifact has to be the scorer too, not always the forest."""
    import joblib

    out = tmp_path / "model.joblib"
    report = train_and_evaluate(_linear_table(n=70, noise=0.5, seed=3), model_out_path=str(out))

    saved = joblib.load(out)
    assert _resolve(saved["model"]) == report.best_model_name
    assert saved["feature_columns"] == FEATURE_COLUMNS


def _result(name: str, roc_auc: float, f1: float) -> EvalResult:
    return EvalResult(
        model_name=name,
        precision=0.0,
        recall=0.0,
        f1=f1,
        roc_auc=roc_auc,
        average_precision=0.0,
        positive_rate=0.5,
        n_test=10,
    )


def test_selection_ranks_on_roc_auc_not_f1():
    """ROC-AUC is the selection metric because the product output is a
    ranking, not a decision at the 0.5 threshold F1 is scored at."""
    higher_auc = _result("random_forest", roc_auc=0.90, f1=0.40)
    higher_f1 = _result("logistic_regression_baseline", roc_auc=0.70, f1=0.80)

    assert max([higher_f1, higher_auc], key=_selection_key) is higher_auc


def test_selection_falls_back_to_f1_when_roc_auc_ties():
    tied_low = _result("random_forest", roc_auc=0.80, f1=0.40)
    tied_high = _result("logistic_regression_baseline", roc_auc=0.80, f1=0.60)

    assert max([tied_low, tied_high], key=_selection_key) is tied_high


def test_nan_roc_auc_never_wins_by_list_order():
    """`roc_auc` is NaN on a single-class test split. NaN comparisons are
    always False, so without an explicit guard `max` would pick by list
    order while appearing to compare scores — including picking the NaN."""
    nan_first = _result("random_forest", roc_auc=float("nan"), f1=0.10)
    real = _result("logistic_regression_baseline", roc_auc=0.60, f1=0.50)

    assert max([nan_first, real], key=_selection_key) is real
    assert max([real, nan_first], key=_selection_key) is real


def test_report_to_dict_carries_the_importance_kind():
    """The dashboard labels its panel from this field, so it has to survive
    serialization rather than being dropped on the way out."""
    report = train_and_evaluate(_interaction_table(n=400, seed=7))
    payload = report.to_dict()

    assert payload["best_model_name"] == report.best_model_name
    assert payload["feature_importance_kind"] == report.feature_importance_kind
