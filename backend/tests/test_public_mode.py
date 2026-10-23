from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from evomind.api import main

client = TestClient(main.app)


def test_public_demo_refuses_ai_recommendations(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC", True)
    monkeypatch.delenv("EVOMIND_PUBLIC_AI", raising=False)
    resp = client.post("/recommend", json={"repo": "https://github.com/o/r", "file_path": "a.py"})
    assert resp.status_code == 403


def test_public_demo_refuses_posting_pr_comments(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC", True)
    resp = client.post("/pr-risk", json={"repo": "https://github.com/o/r", "pr_number": 1, "post_comment": True})
    assert resp.status_code == 403


def test_public_demo_only_accepts_github_urls(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC", True)
    try:
        main._check_public_limits("https://gitlab.com/a/b")
    except ValueError as exc:
        assert "public GitHub repositories" in str(exc)
    else:
        raise AssertionError("expected a ValueError")


def test_results_are_remembered_per_repo_and_reused():
    main._last_result.clear()
    main._result_meta.clear()
    main._remember("https://github.com/a/one", "first", (365, 0.65, False))
    main._remember("https://github.com/b/two", "second", (365, 0.65, False))
    assert main._recent("https://github.com/a/one", (365, 0.65, False)) == "first"
    assert main._recent("https://github.com/b/two", (365, 0.65, False)) == "second"
    assert main._recent("https://github.com/a/one", (180, 0.65, False)) is None


def test_only_the_most_recent_results_are_kept():
    main._last_result.clear()
    main._result_meta.clear()
    for i in range(main.MAX_REMEMBERED + 2):
        main._remember(f"https://github.com/o/r{i}", i, ())
    assert len(main._last_result) == main.MAX_REMEMBERED
    assert "https://github.com/o/r0" not in main._last_result


def test_queue_runs_one_analysis_at_a_time_and_reports_position():
    order, messages = [], []

    def job(name, hold):
        with main._turn(messages.append):
            order.append(f"{name}-start")
            time.sleep(hold)
            order.append(f"{name}-end")

    first = threading.Thread(target=job, args=("a", 0.3))
    first.start()
    time.sleep(0.05)
    second = threading.Thread(target=job, args=("b", 0))
    second.start()
    first.join()
    second.join()
    assert order == ["a-start", "a-end", "b-start", "b-end"]
    assert any("#1 in line" in m for m in messages)
