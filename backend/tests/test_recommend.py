import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import groq
import pytest

from evomind.llm.recommend import (
    FileRecommendation,
    RecommendationError,
    generate_recommendation,
)


def _chat_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def _fake_client(response_json: dict) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value = _chat_response(json.dumps(response_json))
    return client


def test_generate_recommendation_parses_json_response():
    payload = {
        "summary": "This file mixes routing and business logic.",
        "suggestions": [
            {
                "issue": "God function handles validation, DB access, and rendering.",
                "recommendation": "Split into separate validate/persist/render functions.",
                "priority": "high",
            }
        ],
    }
    client = _fake_client(payload)

    result = generate_recommendation(
        file_path="app.py",
        risk_score=0.72,
        metrics={"loc": 400, "avg_cyclomatic_complexity": 12.0},
        source="def handler(): pass",
        client=client,
    )

    assert isinstance(result, FileRecommendation)
    assert result.summary == payload["summary"]
    assert result.suggestions[0].priority == "high"

    client.chat.completions.create.assert_called_once()
    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert "app.py" in call_kwargs["messages"][1]["content"]
    assert "72%" in call_kwargs["messages"][1]["content"]


def test_generate_recommendation_strips_markdown_fences():
    payload = {"summary": "ok", "suggestions": []}
    client = MagicMock()
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    client.chat.completions.create.return_value = _chat_response(fenced)

    result = generate_recommendation(
        file_path="a.py", risk_score=0.5, metrics={}, source="pass", client=client
    )
    assert result.summary == "ok"


def test_generate_recommendation_truncates_long_source():
    client = _fake_client({"summary": "ok", "suggestions": []})
    huge_source = "x = 1\n" * 10000

    generate_recommendation(
        file_path="big.py", risk_score=0.5, metrics={}, source=huge_source, client=client
    )

    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "truncated" in prompt


def test_invalid_json_response_raises_recommendation_error():
    client = MagicMock()
    client.chat.completions.create.return_value = _chat_response("not json")

    with pytest.raises(RecommendationError, match="parse"):
        generate_recommendation(
            file_path="a.py", risk_score=0.5, metrics={}, source="pass", client=client
        )


def test_authentication_error_wrapped():
    client = MagicMock()
    client.chat.completions.create.side_effect = groq.AuthenticationError(
        message="bad key", response=MagicMock(status_code=401, headers={}), body=None
    )

    with pytest.raises(RecommendationError, match="GROQ_API_KEY"):
        generate_recommendation(
            file_path="a.py", risk_score=0.5, metrics={}, source="pass", client=client
        )


def test_missing_credentials_wrapped(monkeypatch):
    def _raise_no_key(*args, **kwargs):
        raise groq.GroqError("The api_key client option must be set")

    monkeypatch.setattr(groq, "Groq", _raise_no_key)
    with pytest.raises(RecommendationError, match="GROQ_API_KEY"):
        generate_recommendation(
            file_path="a.py", risk_score=0.5, metrics={}, source="pass", client=None
        )
