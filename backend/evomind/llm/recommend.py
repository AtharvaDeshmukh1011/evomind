from __future__ import annotations

import json
from typing import Literal

import groq
from pydantic import BaseModel, Field, ValidationError

MODEL = "openai/gpt-oss-120b"
MAX_SOURCE_CHARS = 12000

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
    pass


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
    client: groq.Groq | None = None,
) -> FileRecommendation:
    prompt = _build_prompt(file_path, risk_score, metrics, source)

    try:
        client = client or groq.Groq()
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
    except groq.AuthenticationError as exc:
        raise RecommendationError("Groq API key missing or invalid — set GROQ_API_KEY.") from exc
    except groq.RateLimitError as exc:
        raise RecommendationError("Rate limited by the Groq API — try again shortly.") from exc
    except groq.APIStatusError as exc:
        raise RecommendationError(f"Groq API error: {exc.message}") from exc
    except groq.APIConnectionError as exc:
        raise RecommendationError("Could not reach the Groq API — check network connectivity.") from exc
    except groq.GroqError as exc:
        raise RecommendationError("Groq API key missing or invalid — set GROQ_API_KEY.") from exc

    text = (response.choices[0].message.content or "").strip()
    return _parse_recommendation(text)


def _parse_recommendation(text: str) -> FileRecommendation:
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
