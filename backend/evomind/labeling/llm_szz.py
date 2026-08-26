"""LLM-assisted refinement of SZZ-identified bug-inducing commits.

Plain SZZ (szz.py) traces a fix's changed lines back to whichever commit's
`git blame` last touched them — but blame is a purely line-level heuristic,
so it produces real false positives: a candidate "inducing" commit can be a
formatting pass, a rename, or an unrelated refactor that happened to touch
the same line, not the change that actually introduced the defect.

This follows LLM4SZZ (Zhou et al., 2025 — arXiv:2504.01404, ACM Proceedings
on Software Engineering): use an LLM, given the fix's own diff and a
candidate's own diff, to assess whether that candidate is a plausible
genuine bug-inducing change rather than a blame false positive. This is an
applied technique following a published approach — not a novel
contribution of this project. Related work exploring similar LLM-assisted
SZZ variants: AgenticSZZ, AgentSZZ, MAS-SZZ.

Runs against Groq (free API tier, no paid key required — same as
evomind/llm/recommend.py). Needs GROQ_API_KEY; see https://console.groq.com.

Scope: this only ever *removes* candidates plain SZZ would have accepted
(false-positive filtering) — it never adds a candidate blame-based tracing
didn't already find. Opt-in and bounded the same way szz.py's
`refine_labels_with_szz` already is: only positively-labeled files, and
only candidates that already pass the cutoff-date check (no LLM call spent
on a candidate the date alone already disqualifies).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import groq
import pandas as pd
from pydantic import BaseModel, ValidationError

from evomind.ingestion.git_miner import FileCommitRecord
from evomind.labeling.szz import commit_diff_text, commit_message, trace_inducing_commits

MODEL = "openai/gpt-oss-120b"
MAX_DIFF_CHARS = 4000

SYSTEM_PROMPT = (
    "You are assisting a bug-inducing-commit detector (SZZ). Git's `blame` "
    "identified a CANDIDATE commit as the last one to touch the lines a "
    "later FIX commit corrected — but blame is purely line-level and often "
    "wrong: it can point to a formatting pass, a rename, an unrelated "
    "refactor, or code motion that never changed behavior. Given the FIX's "
    "diff and the CANDIDATE's own diff, decide whether the CANDIDATE "
    "plausibly introduced the defect the FIX corrects, or is a false "
    "positive from blame's line tracking.\n\n"
    "Respond with ONLY a single JSON object (no markdown fences, no "
    "commentary) matching exactly this shape:\n"
    '{"is_plausible_cause": true|false, "reason": "one short sentence"}'
)


class InducingAssessment(BaseModel):
    is_plausible_cause: bool
    reason: str


class LLMSZZError(RuntimeError):
    """Raised when the LLM call fails; carries a user-facing message."""


@dataclass
class AssessmentStats:
    """Visibility into how much LLM assessment actually happened — so a
    caller enabling this feature without a usable API key sees that it
    silently fell back to plain-SZZ behavior, rather than assuming
    filtering occurred when it didn't."""
    assessed: int = 0
    fallback: int = 0


def _build_prompt(file_path: str, fix_diff: str, candidate_diff: str, candidate_message: str) -> str:
    fix_diff = fix_diff[:MAX_DIFF_CHARS]
    candidate_diff = candidate_diff[:MAX_DIFF_CHARS]
    return f"""File: {file_path}

FIX commit's diff:
```
{fix_diff}
```

CANDIDATE commit's diff (message: "{candidate_message}"):
```
{candidate_diff}
```

Is the CANDIDATE a plausible genuine bug-inducing change for this fix?"""


def _parse_assessment(text: str) -> InducingAssessment:
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
        return InducingAssessment.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMSZZError(f"Could not parse the model's response as JSON: {exc}") from exc


def assess_candidate(
    file_path: str,
    fix_diff: str,
    candidate_diff: str,
    candidate_message: str,
    client: groq.Groq | None = None,
) -> InducingAssessment:
    prompt = _build_prompt(file_path, fix_diff, candidate_diff, candidate_message)

    try:
        client = client or groq.Groq()
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=512,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
    except groq.AuthenticationError as exc:
        raise LLMSZZError("Groq API key missing or invalid — set GROQ_API_KEY.") from exc
    except groq.RateLimitError as exc:
        raise LLMSZZError("Rate limited by the Groq API — try again shortly.") from exc
    except groq.APIStatusError as exc:
        raise LLMSZZError(f"Groq API error: {exc.message}") from exc
    except groq.APIConnectionError as exc:
        raise LLMSZZError("Could not reach the Groq API — check network connectivity.") from exc
    except groq.GroqError as exc:
        # Raised at client construction (e.g. no API key configured at all),
        # before any network call, so no HTTP-level error/status exists yet.
        raise LLMSZZError("Groq API key missing or invalid — set GROQ_API_KEY.") from exc

    text = (response.choices[0].message.content or "").strip()
    return _parse_assessment(text)


def had_bug_before_cutoff_llm_assisted(
    repo_path: str,
    file_path: str,
    candidate_fix_commits: list[str],
    cutoff: datetime,
    client: groq.Groq | None = None,
    stats: AssessmentStats | None = None,
) -> bool:
    """Same contract as szz.had_bug_before_cutoff, but each blame-identified
    candidate that already passes the cutoff-date check is additionally
    assessed by an LLM (LLM4SZZ-style) before being accepted, filtering out
    false positives (formatting/rename/unrelated-refactor candidates) that
    plain blame-based SZZ can't distinguish from a real inducing change.

    Falls back to accepting the candidate (plain-SZZ behavior) if the LLM
    call itself fails for it — a missing API key or a transient error
    should degrade to the existing heuristic, not silently drop a label
    plain SZZ would have kept, and not crash the analysis.
    """
    for fix_hash in candidate_fix_commits:
        fix_diff = None  # fetched lazily — only if there's a candidate to assess
        for candidate in trace_inducing_commits(repo_path, fix_hash, file_path):
            if candidate.author_date > cutoff:
                continue  # date alone disqualifies it; no LLM call needed

            if fix_diff is None:
                fix_diff = commit_diff_text(repo_path, fix_hash, file_path)

            candidate_diff = commit_diff_text(repo_path, candidate.commit_hash, file_path)
            candidate_message = commit_message(repo_path, candidate.commit_hash)

            try:
                assessment = assess_candidate(file_path, fix_diff, candidate_diff, candidate_message, client)
            except LLMSZZError:
                if stats is not None:
                    stats.fallback += 1
                return True

            if stats is not None:
                stats.assessed += 1
            if assessment.is_plausible_cause:
                return True
    return False


def refine_labels_with_llm_szz(
    train_df: pd.DataFrame,
    mined_records: list[FileCommitRecord],
    repo_path: str,
    cutoff: datetime,
    horizon_end: datetime,
    client: groq.Groq | None = None,
) -> tuple[pd.DataFrame, AssessmentStats]:
    """Same contract and scope as szz.refine_labels_with_szz (only re-checks
    currently-positive files, bounded cost), but each candidate is filtered
    through `had_bug_before_cutoff_llm_assisted` instead of the plain
    date-only check — see this module's docstring for why.

    Returns the refined DataFrame plus stats on how many candidates were
    actually LLM-assessed vs. fell back to plain-SZZ behavior, so a caller
    can tell whether the filtering actually ran (e.g. it silently no-ops,
    by design, when no API key is configured).
    """
    positive_files = set(train_df.loc[train_df["is_bug_prone"] == 1, "file_path"])
    stats = AssessmentStats()
    if not positive_files:
        return train_df, stats

    fixes_by_file: dict[str, list[str]] = {}
    for rec in mined_records:
        if rec.file_path in positive_files and rec.is_bug_fix and cutoff < rec.author_date <= horizon_end:
            fixes_by_file.setdefault(rec.file_path, []).append(rec.commit_hash)

    confirmed = {
        file_path
        for file_path, fix_hashes in fixes_by_file.items()
        if had_bug_before_cutoff_llm_assisted(repo_path, file_path, fix_hashes, cutoff, client, stats)
    }

    refined = train_df.copy()
    still_positive = refined["is_bug_prone"] == 1
    refined.loc[still_positive, "is_bug_prone"] = (
        refined.loc[still_positive, "file_path"].isin(confirmed).astype(int)
    )
    return refined, stats
