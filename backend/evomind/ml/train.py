"""Trains and evaluates bug-proneness classifiers on the feature table.

Fits a Random Forest against a Logistic Regression baseline, since the
literature review (Ajibode et al., 2024) found ensemble methods like Random
Forest consistently outperform simpler linear models on this task — but
selects between them on measured held-out performance rather than assuming
it, and the selected model is the one that goes on to score files in
`evomind/pipeline.py`. See `_selection_key` for why the selection metric is
ROC-AUC rather than F1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

FEATURE_COLUMNS = [
    "num_commits",
    "num_authors",
    "lines_added_total",
    "lines_removed_total",
    "churn",
    "num_prior_bug_fixes",
    "age_days",
    "recency_days",
    "loc",
    "sloc",
    "avg_cyclomatic_complexity",
    "max_cyclomatic_complexity",
    "function_count",
    "maintainability_index",
    "halstead_volume",
    "halstead_difficulty",
]

LABEL_COLUMN = "is_bug_prone"


@dataclass
class EvalResult:
    model_name: str
    precision: float
    recall: float
    f1: float
    roc_auc: float
    average_precision: float
    positive_rate: float
    n_test: int


@dataclass
class TrainingReport:
    results: list[EvalResult] = field(default_factory=list)
    best_model_name: str = ""
    feature_importances: dict[str, float] = field(default_factory=dict)
    # Which quantity `feature_importances` actually holds — it differs by
    # model (see `_feature_importances`), so the dashboard can label it
    # rather than always claiming "Random Forest importances".
    feature_importance_kind: str = ""
    model: object = None  # the selected model — the one that scores files

    def to_dict(self) -> dict:
        return {
            "results": [r.__dict__ for r in self.results],
            "best_model_name": self.best_model_name,
            "feature_importances": self.feature_importances,
            "feature_importance_kind": self.feature_importance_kind,
        }


def _evaluate(name: str, model, X_test, y_test) -> EvalResult:
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    return EvalResult(
        model_name=name,
        precision=precision_score(y_test, y_pred, zero_division=0),
        recall=recall_score(y_test, y_pred, zero_division=0),
        f1=f1_score(y_test, y_pred, zero_division=0),
        roc_auc=roc_auc_score(y_test, y_proba) if y_test.nunique() > 1 else float("nan"),
        average_precision=average_precision_score(y_test, y_proba)
        if y_test.nunique() > 1
        else float("nan"),
        positive_rate=y_test.mean(),
        n_test=len(y_test),
    )


def _fit_models(X_train: pd.DataFrame, y_train: pd.Series, random_state: int):
    baseline = Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "clf",
                LogisticRegression(max_iter=1000, class_weight="balanced"),
            ),
        ]
    )
    baseline.fit(X_train, y_train)

    forest = RandomForestClassifier(
        n_estimators=300,
        max_depth=None,
        min_samples_leaf=2,
        class_weight="balanced_subsample",
        random_state=random_state,
        n_jobs=-1,
    )
    forest.fit(X_train, y_train)
    return baseline, forest


def _selection_key(result: EvalResult) -> tuple[float, float]:
    """Ranks candidate models: ROC-AUC first, F1 as a tiebreak.

    ROC-AUC rather than F1 because the product output is a *ranking* of
    files by risk score (see `pipeline.py`), not a binary accept/reject at
    the 0.5 probability threshold that precision/recall/F1 are computed at.
    ROC-AUC measures exactly the property the ranking depends on — whether
    a genuinely bug-prone file is scored above a clean one — while F1
    measures quality at one arbitrary cut point. The rolling-origin runs
    make the difference concrete: on Click, ROC-AUC stayed stable across
    folds (0.795-0.882) while F1 swung far wider (0.417-0.690), so F1 is
    the noisier quantity to select on.

    `roc_auc` is NaN when a test split comes out single-class. Map that to
    -1.0 explicitly: NaN comparisons are always False, so leaving it in
    would let `max` pick by list order while looking like it compared
    scores.
    """
    roc_auc = -1.0 if math.isnan(result.roc_auc) else result.roc_auc
    return (roc_auc, result.f1)


def _feature_importances(model) -> tuple[dict[str, float], str]:
    """Per-feature contribution for whichever model was selected.

    The two models expose different quantities, so this can't just read one
    attribute. Random Forest has `feature_importances_` (mean decrease in
    impurity). The logistic baseline has none — its comparable quantity is
    the magnitude of each coefficient, which is only meaningful because the
    pipeline standardizes features first, putting every coefficient on the
    same scale. Normalized to sum to 1 so both kinds render against the
    same axis in the dashboard, and returned with a label so the UI can say
    which one it's showing instead of guessing.
    """
    if hasattr(model, "feature_importances_"):
        values = model.feature_importances_.tolist()
        kind = "mean decrease in impurity (Random Forest)"
    else:
        magnitudes = [abs(float(c)) for c in model.named_steps["clf"].coef_[0]]
        total = sum(magnitudes)
        values = [m / total for m in magnitudes] if total else magnitudes
        kind = "absolute standardized coefficient (Logistic Regression)"

    ranked = dict(sorted(zip(FEATURE_COLUMNS, values), key=lambda kv: kv[1], reverse=True))
    return ranked, kind


def _build_report(baseline, forest, X_test: pd.DataFrame, y_test: pd.Series) -> TrainingReport:
    candidates = {
        "logistic_regression_baseline": baseline,
        "random_forest": forest,
    }

    report = TrainingReport()
    report.results.append(_evaluate("logistic_regression_baseline", baseline, X_test, y_test))
    report.results.append(_evaluate("random_forest", forest, X_test, y_test))

    best = max(report.results, key=_selection_key)
    report.best_model_name = best.model_name
    # The selected model is the one that actually scores files downstream.
    # Reporting one winner and then scoring with the other would make
    # `best_model_name` a label with nothing behind it — and the feature
    # importances would describe a model the risk scores never came from.
    report.model = candidates[best.model_name]
    report.feature_importances, report.feature_importance_kind = _feature_importances(report.model)
    return report


def train_and_evaluate(
    df: pd.DataFrame,
    test_size: float = 0.3,
    random_state: int = 42,
    model_out_path: str | None = None,
) -> TrainingReport:
    """Single random (stratified) train/test split within one snapshot.

    Fast enough for interactive use, but the split is arbitrary with respect
    to time — see `train_on_evaluate_on` for temporal (rolling-origin)
    validation instead, which is closer to what rigorous defect-prediction
    papers use but requires multiple already-computed feature tables.
    """
    X = df[FEATURE_COLUMNS]
    y = df[LABEL_COLUMN]

    stratify = y if y.nunique() > 1 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=stratify
    )

    baseline, forest = _fit_models(X_train, y_train, random_state)
    report = _build_report(baseline, forest, X_test, y_test)

    if model_out_path:
        joblib.dump(
            {"model": report.model, "feature_columns": FEATURE_COLUMNS},
            model_out_path,
        )

    return report


def train_on_evaluate_on(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    random_state: int = 42,
) -> TrainingReport:
    """Trains fresh models on all of `train_df` and evaluates purely on
    `test_df` — no internal split, since train/test here are already two
    different time periods (rolling-origin / walk-forward validation),
    rather than an arbitrary random partition of one snapshot.
    """
    X_train, y_train = train_df[FEATURE_COLUMNS], train_df[LABEL_COLUMN]
    X_test, y_test = test_df[FEATURE_COLUMNS], test_df[LABEL_COLUMN]

    baseline, forest = _fit_models(X_train, y_train, random_state)
    return _build_report(baseline, forest, X_test, y_test)
