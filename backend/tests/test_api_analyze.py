from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from evomind.api import main
from evomind.architecture.dependency_graph import CouplingMetrics, DependencyGraph, ImportEdge
from evomind.ml.train import EvalResult, FEATURE_COLUMNS, TrainingReport
from evomind.pipeline import PipelineResult

client = TestClient(main.app)


def _fake_pipeline_result() -> PipelineResult:
    metrics_row = {col: 1 for col in FEATURE_COLUMNS}
    feature_table = pd.DataFrame([{**metrics_row, "is_bug_prone": 1}, {**metrics_row, "is_bug_prone": 0}])
    current_metrics = pd.DataFrame(
        [
            {"file_path": "app.py", **metrics_row, "risk_score": 0.9},
            {"file_path": "util.py", **metrics_row, "risk_score": 0.2},
        ]
    )

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

    graph = DependencyGraph(files=["app.py", "util.py"], edges=[ImportEdge("app.py", "util.py")])
    coupling = [
        CouplingMetrics(file_path="app.py", afferent=0, efferent=1, instability=1.0),
        CouplingMetrics(file_path="util.py", afferent=1, efferent=0, instability=0.0),
    ]

    return PipelineResult(
        repo="https://example.com/repo.git",
        cutoff="2024-01-01T00:00:00",
        horizon_days=365,
        feature_table=feature_table,
        training_report=report,
        file_risk_scores=current_metrics[["file_path", "risk_score"]],
        current_metrics=current_metrics,
        latest_snapshots={"app.py": "import util\n", "util.py": ""},
        dependency_graph=graph,
        coupling=coupling,
        cyclic_groups=[["app.py", "util.py"]],
    )


def test_analyze_includes_dependency_fields():
    main._last_result.clear()
    with patch("evomind.api.main.run_pipeline", return_value=_fake_pipeline_result()):
        resp = client.post("/analyze", json={"repo": "https://example.com/repo.git"})

    assert resp.status_code == 200
    body = resp.json()

    assert body["dependency_edge_count"] == 1
    assert body["cyclic_groups"] == [["app.py", "util.py"]]

    coupled = {c["file_path"]: c for c in body["most_coupled_files"]}
    assert coupled["app.py"]["efferent"] == 1
    assert coupled["app.py"]["instability"] == 1.0
    assert coupled["util.py"]["afferent"] == 1
