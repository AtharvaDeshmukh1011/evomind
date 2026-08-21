"""LLM-generated refactoring recommendations for a risky file.

Grounds the recommendation in the same evidence the ML model saw: the
predicted risk score, the file's code/process metrics, and an excerpt of
its actual source — not just the metrics in isolation.
"""

from __future__ import annotations

import json
from typing import Literal

import anthropic
from pydantic import BaseModel, Field, ValidationError

MODEL = "claude-opus-5"
MAX_SOURCE_CHARS = 12000

# The installed anthropic SDK version in this project predates the
# messages.parse()/output_config structured-output helpers, so recommendations
# are requested as plain JSON text and validated manually with Pydantic below
# — this pattern works against any SDK version, current or older.
SYSTEM_PROMPT = (
    "You are a senior software engineer reviewing a file that a machine learning "
    "model — trained on this repository's own Git history and code metrics — has "
    "flagged as likely to be involved in a future bug fix. Give specific, "
    "actionable refactoring recommendations grounded in the actual code shown, "
    "not generic advice. Reference concrete function or class names when relevant. "
    "If the metrics and code don't actually support high risk, say so plainly "
    "rather than inventing problems.\n\n"
    "Respond with ONLY a single JSON object (no markdown fences, no commentary) "
    "matching exactly this shape:\n"
    '{"summary": "1-3 sentence assessment", '
    '"suggestions": [{"issue": "...", "recommendation": "...", '
    '"priority": "low"|"medium"|"high"}]}'
)


class RefactoringSuggestion(BaseModel):
    issue: str = Field(description="A specific problem observed in this file")
    recommendation: str = Field(description="A concrete, actionable refactoring step")
    priority: Literal["low", "medium", "high"]


class FileRecommendation(BaseModel):
    summary: str = Field(description="1-3 sentence assessment of why this file is (or isn't) risky")
    suggestions: list[RefactoringSuggestion]


class RecommendationError(RuntimeError):
    """Raised when the LLM call fails; carries a user-facing message."""


def _build_prompt(file_path: str, risk_score: float, metrics: dict, source: str) -> str:
    truncated = source[:MAX_SOURCE_CHARS]
    note = "" if len(source) <= MAX_SOURCE_CHARS else f"\n(truncated — showing first {MAX_SOURCE_CHARS} of {len(source)} characters)"

    return f"""File: {file_path}
Predicted bug-proneness risk: {risk_score:.0%}

Code and process metrics:
{json.dumps(metrics, indent=2)}

Source:{note}
```
{truncated}
```

Identify what specifically makes this file risky (or explain why the model's
score looks off) and recommend concrete refactoring steps."""


def generate_recommendation(
    file_path: str,
    risk_score: float,
    metrics: dict,
    source: str,
    client: anthropic.Anthropic | None = None,
) -> FileRecommendation:
    client = client or anthropic.Anthropic()
    prompt = _build_prompt(file_path, risk_score, metrics, source)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError as exc:
        raise RecommendationError(
            "Anthropic API key missing or invalid — set ANTHROPIC_API_KEY."
        ) from exc
    except TypeError as exc:
        # The SDK raises a plain TypeError (not AuthenticationError) when no
        # credentials are configured at all — it fails building the request
        # headers before any network call, so no HTTP-level error exists yet.
        if "authentication" in str(exc).lower():
            raise RecommendationError(
                "Anthropic API key missing or invalid — set ANTHROPIC_API_KEY."
            ) from exc
        raise
    except anthropic.RateLimitError as exc:
        raise RecommendationError("Rate limited by the Anthropic API — try again shortly.") from exc
    except anthropic.APIStatusError as exc:
        raise RecommendationError(f"Anthropic API error: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RecommendationError("Could not reach the Anthropic API — check network connectivity.") from exc

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    return _parse_recommendation(text)


def _parse_recommendation(text: str) -> FileRecommendation:
    # Models occasionally wrap JSON in ```json fences despite instructions not to.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
        return FileRecommendation.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise RecommendationError(f"Could not parse the model's response as JSON: {exc}") from exc
