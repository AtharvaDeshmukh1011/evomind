from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from evomind.api import main
from evomind.architecture.dependency_graph import DependencyGraph
from evomind.ml.train import EvalResult, FEATURE_COLUMNS, TrainingReport
from evomind.pipeline import PipelineResult

client = TestClient(main.app)


def _fake_pipeline_result() -> PipelineResult:
    metrics_row = {col: 1 for col in FEATURE_COLUMNS}
    feature_table = pd.DataFrame([{**metrics_row, "is_bug_prone": 1}, {**metrics_row, "is_bug_prone": 0}])
    current_metrics = pd.DataFrame([{"file_path": "app.py", **metrics_row, "risk_score": 0.9}])
    report = TrainingReport(
        results=[
            EvalResult(
                model_name="random_forest", precision=0.8, recall=0.7, f1=0.75,
                roc_auc=0.9, average_precision=0.85, positive_rate=0.5, n_test=10,
            )
        ],
        best_model_name="random_forest",
        feature_importances={"loc": 0.5},
    )
    return PipelineResult(
        repo="https://example.com/repo.git",
        cutoff="2024-01-01T00:00:00",
        horizon_days=365,
        feature_table=feature_table,
        training_report=report,
        file_risk_scores=current_metrics[["file_path", "risk_score"]],
        current_metrics=current_metrics,
        latest_snapshots={"app.py": "x = 1\n"},
        dependency_graph=DependencyGraph(),
        coupling=[],
        cyclic_groups=[],
    )


def _parse_sse(body: str) -> list[tuple[str, str]]:
    events = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event = next(l.split(": ", 1)[1] for l in lines if l.startswith("event:"))
        data = next(l.split(": ", 1)[1] for l in lines if l.startswith("data:"))
        events.append((event, data))
    return events


def _fake_run_pipeline(*, repo, horizon_days, train_fraction, on_progress=None, use_llm_szz=False):
    if on_progress:
        on_progress("Mining commit history…")
        on_progress("Training models…")
    return _fake_pipeline_result()


def test_stream_emits_progress_then_result():
    main._last_result.clear()
    with patch("evomind.api.main.run_pipeline", side_effect=_fake_run_pipeline):
        with client.stream("GET", "/analyze/stream", params={"repo": "https://example.com/repo.git"}) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())

    events = _parse_sse(body)
    kinds = [e for e, _ in events]
    assert kinds.count("progress") == 2
    assert kinds[-1] == "result"

    import json
    result_data = json.loads(events[-1][1])
    assert result_data["repo"] == "https://example.com/repo.git"
    assert result_data["best_model"] == "random_forest"

    # The streamed result must also populate the /recommend cache, same as POST /analyze.
    assert "https://example.com/repo.git" in main._last_result


def test_stream_emits_error_event_on_value_error():
    main._last_result.clear()

    def raising_pipeline(**kwargs):
        raise ValueError("not enough data")

    with patch("evomind.api.main.run_pipeline", side_effect=raising_pipeline):
        with client.stream("GET", "/analyze/stream", params={"repo": "https://example.com/repo.git"}) as resp:
            body = "".join(resp.iter_text())

    events = _parse_sse(body)
    assert events[-1][0] == "error"
    import json
    error_data = json.loads(events[-1][1])
    assert error_data["status"] == 422
    assert "not enough data" in error_data["detail"]
