from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from evomind.api import main
from evomind.integrations.github import COMMENT_MARKER, ChangedFile
from evomind.ml.explain import Reason
from evomind.pr_risk import build_pr_report, render_comment


def _result():
    reasons = [Reason("churn", "churn", 6405.0, 0.98, 0.14)]
    scores = pd.DataFrame([
        {"file_path": "src\\app.py", "risk_score": 0.72, "reasons": reasons, "trend_delta": 0.21},
        {"file_path": "src/util.py", "risk_score": 0.20, "reasons": [], "trend_delta": float("nan")},
        {"file_path": "src/old_name.py", "risk_score": 0.55, "reasons": [], "trend_delta": -0.05},
    ])
    report = SimpleNamespace(
        best_model_name="random_forest",
        results=[SimpleNamespace(model_name="random_forest", roc_auc=0.81)],
    )
    return SimpleNamespace(file_risk_scores=scores, training_report=report, horizon_days=365)


def _report(changed):
    return build_pr_report(_result(), "o/r", 7, changed)


def test_changed_files_are_matched_across_path_separators():
    report = _report([ChangedFile("src/app.py", "modified")])
    assert report.files[0].risk_score == 0.72
    assert report.files[0].band == "Critical"
    assert report.files[0].reasons[0].feature == "churn"


def test_renamed_file_falls_back_to_its_previous_path():
    report = _report([ChangedFile("src/new_name.py", "renamed", previous_path="src/old_name.py")])
    assert report.files[0].risk_score == 0.55


def test_unscored_files_say_why():
    report = _report([
        ChangedFile("src/brand_new.py", "added"),
        ChangedFile("README.md", "modified"),
        ChangedFile("src/gone.py", "removed"),
        ChangedFile("src/mystery.py", "modified"),
    ])
    notes = {f.path: f.note for f in report.files}
    assert notes["src/brand_new.py"] == "new file — no history yet"
    assert notes["README.md"] == "not analysed (file type not supported)"
    assert notes["src/gone.py"] == "removed in this PR"
    assert notes["src/mystery.py"] == "no history in the analysed revision"
    assert all(f.risk_score is None for f in report.files)


def test_riskiest_first_then_unscored():
    report = _report([ChangedFile("README.md", "modified"), ChangedFile("src/util.py", "modified"),
                      ChangedFile("src/app.py", "modified")])
    assert [f.path for f in report.files] == ["src/app.py", "src/util.py", "README.md"]


def test_nan_trend_becomes_none():
    assert _report([ChangedFile("src/util.py", "modified")]).files[0].trend_delta is None


def test_high_risk_threshold_is_serious_or_above():
    report = _report([ChangedFile("src/app.py", "modified"), ChangedFile("src/old_name.py", "modified"),
                      ChangedFile("src/util.py", "modified")])
    assert [f.path for f in report.high_risk] == ["src/app.py", "src/old_name.py"]
    assert report.max_risk == 0.72


def test_comment_carries_marker_headline_and_reasons():
    body = render_comment(_report([ChangedFile("src/app.py", "modified"), ChangedFile("README.md", "modified")]))
    assert body.startswith(COMMENT_MARKER)
    assert "**1 high-risk file**" in body
    assert "| `src/app.py` | 🔴 0.72 Critical | ▲ +0.21 | churn 6,405 (top 2%) |" in body
    assert "`README.md` — not analysed (file type not supported)" in body
    assert "ROC-AUC 0.81" in body


def test_comment_when_nothing_risky():
    body = render_comment(_report([ChangedFile("src/util.py", "modified")]))
    assert "No high-risk files touched." in body


client = TestClient(main.app)
SECRET = "test-secret"


def _post(event, payload, secret=SECRET):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/webhook/github", content=body,
                       headers={"X-GitHub-Event": event, "X-Hub-Signature-256": sig})


PR_PAYLOAD = {"action": "opened", "repository": {"html_url": "https://github.com/o/r"},
              "pull_request": {"number": 7}}


def test_webhook_disabled_without_a_secret(monkeypatch):
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    assert _post("pull_request", PR_PAYLOAD).status_code == 503


def test_webhook_rejects_a_forged_signature(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    with patch.object(main, "_run_webhook_check") as run:
        assert _post("pull_request", PR_PAYLOAD, secret="attacker").status_code == 401
    run.assert_not_called()


def test_webhook_answers_ping(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    assert _post("ping", {"zen": "hi"}).json() == {"status": "pong"}


def test_webhook_ignores_other_events_and_actions(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    with patch.object(main, "_run_webhook_check") as run:
        assert _post("push", {}).json()["status"] == "ignored"
        assert _post("pull_request", {**PR_PAYLOAD, "action": "closed"}).json()["status"] == "ignored"
    run.assert_not_called()


def test_webhook_accepts_and_schedules_the_check(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    with patch.object(main, "_run_webhook_check") as run:
        resp = _post("pull_request", PR_PAYLOAD)
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"
    run.assert_called_once_with("https://github.com/o/r", 7)


def test_pr_risk_endpoint_reports_without_posting():
    fake_client = SimpleNamespace(pull_request_files=lambda o, r, n: [ChangedFile("src/app.py", "modified")],
                                  upsert_comment=lambda *a: (_ for _ in ()).throw(AssertionError("must not post")))
    with patch.object(main, "GitHubClient", return_value=fake_client), \
         patch.object(main, "_analysis_for", return_value=_result()):
        resp = client.post("/pr-risk", json={"repo": "https://github.com/o/r", "pr_number": 7})
    data = resp.json()
    assert resp.status_code == 200
    assert data["high_risk_count"] == 1
    assert data["comment_url"] is None
    assert data["comment_markdown"].startswith(COMMENT_MARKER)


def test_pr_risk_endpoint_rejects_non_github_repo():
    assert client.post("/pr-risk", json={"repo": "https://gitlab.com/a/b", "pr_number": 1}).status_code == 422
