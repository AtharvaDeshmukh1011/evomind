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
    feature_importance_kind: str = ""
    model: object = None

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
    roc_auc = -1.0 if math.isnan(result.roc_auc) else result.roc_auc
    return (roc_auc, result.f1)


def _feature_importances(model) -> tuple[dict[str, float], str]:
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
    report.model = candidates[best.model_name]
    report.feature_importances, report.feature_importance_kind = _feature_importances(report.model)
    return report


def train_and_evaluate(
    df: pd.DataFrame,
    test_size: float = 0.3,
    random_state: int = 42,
    model_out_path: str | None = None,
) -> TrainingReport:
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
    X_train, y_train = train_df[FEATURE_COLUMNS], train_df[LABEL_COLUMN]
    X_test, y_test = test_df[FEATURE_COLUMNS], test_df[LABEL_COLUMN]

    baseline, forest = _fit_models(X_train, y_train, random_state)
    return _build_report(baseline, forest, X_test, y_test)
