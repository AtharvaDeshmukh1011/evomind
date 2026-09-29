from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from evomind.api import main
from evomind.architecture.dependency_graph import DependencyGraph
from evomind.llm.recommend import FileRecommendation, RefactoringSuggestion
from evomind.ml.train import FEATURE_COLUMNS
from evomind.pipeline import PipelineResult

client = TestClient(main.app)


def _fake_pipeline_result() -> PipelineResult:
    metrics_row = {col: 1 for col in FEATURE_COLUMNS}
    current_metrics = pd.DataFrame([{"file_path": "app.py", **metrics_row, "risk_score": 0.81}])

    return PipelineResult(
        repo="https://example.com/repo.git",
        cutoff="2024-01-01T00:00:00",
        horizon_days=365,
        feature_table=pd.DataFrame(),
        training_report=None,
        file_risk_scores=pd.DataFrame([{"file_path": "app.py", "risk_score": 0.81}]),
        current_metrics=current_metrics,
        latest_snapshots={"app.py": "def handler():\n    pass\n"},
        dependency_graph=DependencyGraph(),
        coupling=[],
        cyclic_groups=[],
    )


def test_recommend_serializes_numpy_metrics_without_error():
    main._last_result.clear()
    main._last_result["https://example.com/repo.git"] = _fake_pipeline_result()

    fake_rec = FileRecommendation(
        summary="ok",
        suggestions=[RefactoringSuggestion(issue="x", recommendation="y", priority="low")],
    )
    with patch("evomind.api.main.generate_recommendation", return_value=fake_rec) as mock_gen:
        resp = client.post(
            "/recommend",
            json={"repo": "https://example.com/repo.git", "file_path": "app.py"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["file_path"] == "app.py"
    assert body["suggestions"][0]["priority"] == "low"

    passed_metrics = mock_gen.call_args.kwargs["metrics"]
    for value in passed_metrics.values():
        assert type(value) in (int, float)


def test_recommend_404_when_repo_not_analyzed():
    main._last_result.clear()
    resp = client.post("/recommend", json={"repo": "https://nope.example.com", "file_path": "a.py"})
    assert resp.status_code == 404


def test_recommend_404_when_file_not_in_analysis():
    main._last_result.clear()
    main._last_result["https://example.com/repo.git"] = _fake_pipeline_result()
    resp = client.post(
        "/recommend",
        json={"repo": "https://example.com/repo.git", "file_path": "missing.py"},
    )
    assert resp.status_code == 404
