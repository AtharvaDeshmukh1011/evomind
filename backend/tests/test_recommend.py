import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import pytest

from evomind.llm.recommend import (
    FileRecommendation,
    RecommendationError,
    generate_recommendation,
)


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _fake_client(response_json: dict) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[_text_block(json.dumps(response_json))]
    )
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

    client.messages.create.assert_called_once()
    call_kwargs = client.messages.create.call_args.kwargs
    assert "app.py" in call_kwargs["messages"][0]["content"]
    assert "72%" in call_kwargs["messages"][0]["content"]


def test_generate_recommendation_strips_markdown_fences():
    payload = {"summary": "ok", "suggestions": []}
    client = MagicMock()
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    client.messages.create.return_value = SimpleNamespace(content=[_text_block(fenced)])

    result = generate_recommendation(
        file_path="a.py", risk_score=0.5, metrics={}, source="pass", client=client
    )
    assert result.summary == "ok"


def test_generate_recommendation_truncates_long_source():
    client = _fake_client({"summary": "ok", "suggestions": []})
    huge_source = "x = 1\n" * 10000  # far beyond MAX_SOURCE_CHARS

    generate_recommendation(
        file_path="big.py", risk_score=0.5, metrics={}, source=huge_source, client=client
    )

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "truncated" in prompt


def test_invalid_json_response_raises_recommendation_error():
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(content=[_text_block("not json")])

    with pytest.raises(RecommendationError, match="parse"):
        generate_recommendation(
            file_path="a.py", risk_score=0.5, metrics={}, source="pass", client=client
        )


def test_authentication_error_wrapped():
    client = MagicMock()
    client.messages.create.side_effect = anthropic.AuthenticationError(
        message="bad key", response=MagicMock(status_code=401, headers={}), body=None
    )

    with pytest.raises(RecommendationError, match="ANTHROPIC_API_KEY"):
        generate_recommendation(
            file_path="a.py", risk_score=0.5, metrics={}, source="pass", client=client
        )


def test_missing_credentials_type_error_wrapped():
    # No ANTHROPIC_API_KEY / auth_token / profile: the SDK raises a bare
    # TypeError while building request headers, before any HTTP call.
    client = MagicMock()
    client.messages.create.side_effect = TypeError(
        "Could not resolve authentication method. Expected either api_key or "
        "auth_token to be set."
    )

    with pytest.raises(RecommendationError, match="ANTHROPIC_API_KEY"):
        generate_recommendation(
            file_path="a.py", risk_score=0.5, metrics={}, source="pass", client=client
        )


def test_unrelated_type_error_not_swallowed():
    client = MagicMock()
    client.messages.create.side_effect = TypeError("unexpected keyword argument 'foo'")

    with pytest.raises(TypeError, match="unexpected keyword"):
        generate_recommendation(
            file_path="a.py", risk_score=0.5, metrics={}, source="pass", client=client
        )
