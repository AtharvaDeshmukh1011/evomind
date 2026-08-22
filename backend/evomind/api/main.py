"""EvoMind API: analyze a Git repository and return software evolution risk data."""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from evomind.llm.recommend import RecommendationError, generate_recommendation
from evomind.ml.train import FEATURE_COLUMNS
from evomind.pipeline import PipelineResult, run_pipeline

STATIC_DIR = Path(__file__).resolve().parent / "static"

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    repo: str = Field(..., description="Local path or Git URL, e.g. https://github.com/pallets/flask")
    horizon_days: int = Field(365, ge=30, le=1825, description="Future window used to label bug-proneness during training")
    train_fraction: float = Field(0.65, gt=0.1, lt=0.95, description="Fraction of history used before the training cutoff")
    top_n: int = Field(25, ge=1, le=500, description="Number of highest-risk files to return")
    use_llm_szz: bool = Field(
        False,
        description="LLM4SZZ-style false-positive filtering on top of blame-based SZZ tracing. "
        "Needs ANTHROPIC_API_KEY; silently no-ops (falls back to plain SZZ) without one.",
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
    top_risk_files: list[RiskyFile]
    dependency_edge_count: int
    most_coupled_files: list[CoupledFile]
    cyclic_groups: list[list[str]]
    llm_szz_assessed: int | None = None  # None unless use_llm_szz was requested
    llm_szz_fallback: int | None = None  # candidates the LLM call failed for (e.g. no API key)


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
    return FileResponse(STATIC_DIR / "index.html")


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
