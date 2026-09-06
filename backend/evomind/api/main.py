"""EvoMind API: analyze a Git repository and return software evolution risk data."""

from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from evomind.ingestion.repo_source import is_remote
from evomind.llm.recommend import RecommendationError, generate_recommendation
from evomind.ml.rolling_origin import run_rolling_origin_evaluation
from evomind.ml.train import FEATURE_COLUMNS
from evomind.pipeline import PipelineResult, run_pipeline

load_dotenv()  # picks up GROQ_API_KEY from backend/.env if present

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _validate_repo_arg(repo: str) -> None:
    """A URL is always fine -- it can only ever clone whatever that URL
    already grants access to. A local path is different: this API has no
    concept of "does the caller have permission to read this folder," so
    without a check it would let anyone who can reach the server read *any*
    directory on its filesystem, not just repos they should see. Restrict
    local paths to one explicitly configured root, or reject them outright.

    Raises ValueError (not HTTPException) so it can be caught uniformly
    wherever it's called -- including inside the SSE stream endpoints, where
    raising HTTPException directly would break the stream instead of
    surfacing as a proper `error` event with this message.
    """
    if is_remote(repo):
        return

    allowed_root = os.environ.get("EVOMIND_ALLOWED_LOCAL_REPO_ROOT")
    if not allowed_root:
        raise ValueError(
            "Local repo paths are disabled on this server. Use a Git "
            "URL instead, or set EVOMIND_ALLOWED_LOCAL_REPO_ROOT to opt in."
        )

    resolved_root = Path(allowed_root).resolve()
    resolved_repo = Path(repo).resolve()
    if resolved_root != resolved_repo and resolved_root not in resolved_repo.parents:
        raise ValueError(f"'{repo}' is outside the allowed local repo root ({resolved_root}).")

# Single-demo in-memory cache: the dashboard analyzes one repo at a time, and
# /recommend needs the metrics + source snapshots the preceding /analyze call
# already computed, without re-cloning/re-mining just to fetch one file.
_last_result: dict[str, PipelineResult] = {}

app = FastAPI(
    title="EvoMind API",
    description="AI-powered software evolution intelligence: predictive bug-proneness, "
    "technical debt signals, and risk scoring from Git history and code metrics.",
    version="0.1.0",
)

# The dashboard is served from this same origin, so same-origin requests
# never need CORS at all -- this only matters for a *different* website's JS
# calling this API from a browser. allow_origins=["*"] would let literally
# any site do that; scoped to localhost instead, since that's the only place
# this is actually meant to run.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serves everything under static/ (currently just static/vendor/motion.min.js,
# a self-hosted, pinned copy of https://motion.dev's vanilla-JS build --
# vendored rather than loaded from a CDN so the dashboard has zero runtime
# dependency on internet access, matching every other asset here). index.html
# itself is still served by the explicit "/" route below, not through this.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AnalyzeRequest(BaseModel):
    repo: str = Field(..., description="Local path or Git URL, e.g. https://github.com/pallets/flask")
    horizon_days: int = Field(365, ge=30, le=1825, description="Future window used to label bug-proneness during training")
    train_fraction: float = Field(0.65, gt=0.1, lt=0.95, description="Fraction of history used before the training cutoff")
    top_n: int = Field(25, ge=1, le=500, description="Number of highest-risk files to return")
    use_llm_szz: bool = Field(
        False,
        description="LLM4SZZ-style false-positive filtering on top of blame-based SZZ tracing. "
        "Needs GROQ_API_KEY; silently no-ops (falls back to plain SZZ) without one.",
    )


class ModelEval(BaseModel):
    model_name: str
    precision: float
    recall: float
    f1: float
    roc_auc: float
    average_precision: float
    positive_rate: float
    n_test: int


class RiskyFile(BaseModel):
    file_path: str
    risk_score: float


class CoupledFile(BaseModel):
    file_path: str
    afferent: int  # files that depend on this one
    efferent: int  # files this one depends on
    instability: float


class AnalyzeResponse(BaseModel):
    repo: str
    cutoff: str
    horizon_days: int
    training_files: int
    training_positive_rate: float
    evaluation: list[ModelEval]
    best_model: str
    feature_importances: dict[str, float]
    # Which quantity the importances are — differs by selected model, so the
    # dashboard labels the panel from this instead of hardcoding a model name.
    feature_importance_kind: str = ""
    top_risk_files: list[RiskyFile]
    dependency_edge_count: int
    most_coupled_files: list[CoupledFile]
    cyclic_groups: list[list[str]]
    llm_szz_assessed: int | None = None  # None unless use_llm_szz was requested
    llm_szz_fallback: int | None = None  # candidates the LLM call failed for (e.g. no API key)


class FoldEval(BaseModel):
    train_cutoff: str
    test_cutoff: str
    train_files: int
    test_files: int
    evaluation: list[ModelEval]


class RollingOriginResponse(BaseModel):
    repo: str
    horizon_days: int
    cutoff_fractions: list[float]
    folds: list[FoldEval]
    summary: dict[str, dict[str, float]]  # model_name -> {f1_mean, f1_std, roc_auc_mean, roc_auc_std}


class RecommendRequest(BaseModel):
    repo: str = Field(..., description="Repo previously passed to /analyze")
    file_path: str = Field(..., description="One of the file paths returned by /analyze")


class RefactoringSuggestionResponse(BaseModel):
    issue: str
    recommendation: str
    priority: str


class RecommendResponse(BaseModel):
    file_path: str
    risk_score: float
    summary: str
    suggestions: list[RefactoringSuggestionResponse]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def dashboard() -> FileResponse:
    # No-cache: this file is under active development and a stale browser
    # copy (a plain refresh can serve one without revalidating) has already
    # caused real confusion once -- "I don't see the changes" when the
    # server was serving them fine. Not needed for /static/vendor/*, which
    # is versioned by filename/content rather than edited in place.
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


def _build_analyze_response(result: PipelineResult, top_n: int) -> AnalyzeResponse:
    top_risk = result.file_risk_scores.head(top_n)

    most_coupled = sorted(
        result.coupling, key=lambda c: c.afferent + c.efferent, reverse=True
    )[:top_n]

    return AnalyzeResponse(
        repo=result.repo,
        cutoff=result.cutoff,
        horizon_days=result.horizon_days,
        training_files=len(result.feature_table),
        training_positive_rate=float(result.feature_table["is_bug_prone"].mean()),
        evaluation=[ModelEval(**r.__dict__) for r in result.training_report.results],
        best_model=result.training_report.best_model_name,
        feature_importances=result.training_report.feature_importances,
        feature_importance_kind=result.training_report.feature_importance_kind,
        top_risk_files=[
            RiskyFile(file_path=row.file_path, risk_score=row.risk_score)
            for row in top_risk.itertuples()
        ],
        dependency_edge_count=len(result.dependency_graph.edges),
        most_coupled_files=[
            CoupledFile(
                file_path=c.file_path,
                afferent=c.afferent,
                efferent=c.efferent,
                instability=c.instability,
            )
            for c in most_coupled
            if c.afferent + c.efferent > 0
        ],
        cyclic_groups=result.cyclic_groups,
        llm_szz_assessed=result.llm_szz_stats.assessed if result.llm_szz_stats else None,
        llm_szz_fallback=result.llm_szz_stats.fallback if result.llm_szz_stats else None,
    )


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    try:
        _validate_repo_arg(req.repo)
        result = run_pipeline(
            repo=req.repo,
            horizon_days=req.horizon_days,
            train_fraction=req.train_fraction,
            use_llm_szz=req.use_llm_szz,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _last_result.clear()  # single-demo cache: only ever keep the latest analysis
    _last_result[req.repo] = result

    return _build_analyze_response(result, req.top_n)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/analyze/stream")
def analyze_stream(
    repo: str,
    horizon_days: int = 365,
    train_fraction: float = 0.65,
    top_n: int = 25,
    use_llm_szz: bool = False,
) -> StreamingResponse:
    """Same analysis as POST /analyze, but streamed as Server-Sent Events so
    the dashboard can show real progress during the ~1-3 minute run instead
    of a static "please wait" message. `EventSource` only supports GET, so
    parameters travel in the query string rather than a JSON body.
    """

    def generate() -> Iterator[str]:
        events: queue.Queue = queue.Queue()
        outcome: dict = {}

        def worker() -> None:
            try:
                _validate_repo_arg(repo)
                result = run_pipeline(
                    repo=repo,
                    horizon_days=horizon_days,
                    train_fraction=train_fraction,
                    on_progress=lambda message: events.put(("progress", message)),
                    use_llm_szz=use_llm_szz,
                )
                outcome["result"] = result
            except ValueError as exc:
                outcome["error"] = (422, str(exc))
            except Exception as exc:  # noqa: BLE001 — must reach the client as an SSE error, not crash the stream
                outcome["error"] = (500, f"Unexpected error: {exc}")
            finally:
                events.put(("finished", None))

        threading.Thread(target=worker, daemon=True).start()

        while True:
            kind, payload = events.get()
            if kind == "progress":
                yield _sse("progress", {"message": payload})
            else:
                break

        if "error" in outcome:
            status, detail = outcome["error"]
            yield _sse("error", {"status": status, "detail": detail})
            return

        result = outcome["result"]
        _last_result.clear()
        _last_result[repo] = result
        response = _build_analyze_response(result, top_n)
        yield _sse("result", response.model_dump())

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/rolling-origin/stream")
def rolling_origin_stream(
    repo: str,
    horizon_days: int = 365,
    cutoffs: list[float] = Query(default=[0.5, 0.65, 0.8]),
) -> StreamingResponse:
    """Walk-forward evaluation (evomind/ml/rolling_origin.py) streamed the
    same way as /analyze/stream. Deliberately separate from /analyze: it
    repeats the expensive per-cutoff pipeline work once per fold, so it's
    meant to be triggered on demand as supporting evidence, not run on
    every dashboard analysis.
    """
    fractions = tuple(cutoffs)

    def generate() -> Iterator[str]:
        events: queue.Queue = queue.Queue()
        outcome: dict = {}

        def worker() -> None:
            try:
                _validate_repo_arg(repo)
                result = run_rolling_origin_evaluation(
                    repo=repo,
                    horizon_days=horizon_days,
                    cutoff_fractions=fractions,
                    on_progress=lambda message: events.put(("progress", message)),
                )
                outcome["result"] = result
            except ValueError as exc:
                outcome["error"] = (422, str(exc))
            except Exception as exc:  # noqa: BLE001 — must reach the client as an SSE error, not crash the stream
                outcome["error"] = (500, f"Unexpected error: {exc}")
            finally:
                events.put(("finished", None))

        threading.Thread(target=worker, daemon=True).start()

        while True:
            kind, payload = events.get()
            if kind == "progress":
                yield _sse("progress", {"message": payload})
            else:
                break

        if "error" in outcome:
            status, detail = outcome["error"]
            yield _sse("error", {"status": status, "detail": detail})
            return

        result = outcome["result"]
        # A single fold has no spread to measure -- pandas' .std() over one
        # value is NaN, which plain json.dumps() emits as a bare `NaN` token
        # (valid Python, invalid JSON), breaking the browser's JSON.parse.
        summary = {
            model: {k: (v if v == v else 0.0) for k, v in stats.items()}
            for model, stats in result.summary().items()
        }
        response = RollingOriginResponse(
            repo=repo,
            horizon_days=horizon_days,
            cutoff_fractions=list(fractions),
            folds=[
                FoldEval(
                    train_cutoff=f.train_cutoff,
                    test_cutoff=f.test_cutoff,
                    train_files=f.train_files,
                    test_files=f.test_files,
                    evaluation=[ModelEval(**r.__dict__) for r in f.report.results],
                )
                for f in result.folds
            ],
            summary=summary,
        )
        yield _sse("result", response.model_dump())

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest) -> RecommendResponse:
    result = _last_result.get(req.repo)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No cached analysis for this repo — call /analyze first.",
        )

    row = result.current_metrics[result.current_metrics["file_path"] == req.file_path]
    if row.empty:
        raise HTTPException(status_code=404, detail=f"'{req.file_path}' was not in the last analysis.")
    row = row.iloc[0]

    source = result.latest_snapshots.get(req.file_path)
    if source is None:
        raise HTTPException(status_code=404, detail=f"No source snapshot cached for '{req.file_path}'.")

    # pandas/numpy scalars (int64, float64) aren't JSON-serializable — coerce to native Python types
    metrics = {col: row[col].item() if hasattr(row[col], "item") else row[col] for col in FEATURE_COLUMNS}

    try:
        rec = generate_recommendation(
            file_path=req.file_path,
            risk_score=float(row["risk_score"]),
            metrics=metrics,
            source=source,
        )
    except RecommendationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return RecommendResponse(
        file_path=req.file_path,
        risk_score=float(row["risk_score"]),
        summary=rec.summary,
        suggestions=[
            RefactoringSuggestionResponse(
                issue=s.issue, recommendation=s.recommendation, priority=s.priority
            )
            for s in rec.suggestions
        ],
    )
