import pytest

from evomind.ml.rolling_origin import FoldResult, RollingOriginResult, run_rolling_origin_evaluation
from evomind.ml.train import EvalResult, TrainingReport


def test_rejects_fewer_than_two_cutoffs():
    with pytest.raises(ValueError, match="at least 2"):
        run_rolling_origin_evaluation("https://example.com/repo.git", cutoff_fractions=(0.5,))


def test_rejects_non_increasing_cutoffs():
    with pytest.raises(ValueError, match="increasing"):
        run_rolling_origin_evaluation("https://example.com/repo.git", cutoff_fractions=(0.7, 0.5))


def _fold(model_name: str, f1: float, roc_auc: float) -> FoldResult:
    report = TrainingReport(
        results=[
            EvalResult(
                model_name=model_name, precision=0.5, recall=0.5, f1=f1,
                roc_auc=roc_auc, average_precision=0.5, positive_rate=0.2, n_test=10,
            )
        ]
    )
    return FoldResult(train_cutoff="t1", test_cutoff="t2", train_files=50, test_files=40, report=report)


def test_summary_aggregates_mean_across_folds():
    result = RollingOriginResult(
        repo="x",
        folds=[
            _fold("random_forest", f1=0.6, roc_auc=0.8),
            _fold("random_forest", f1=0.8, roc_auc=0.9),
        ],
    )
    summary = result.summary()
    assert summary["random_forest"]["f1_mean"] == pytest.approx(0.7)
    assert summary["random_forest"]["roc_auc_mean"] == pytest.approx(0.85)


def test_summary_empty_when_no_folds():
    assert RollingOriginResult(repo="x", folds=[]).summary() == {}
