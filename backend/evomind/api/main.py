from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from evomind.ingestion.repo_source import is_remote
from evomind.integrations.github import GitHubClient, GitHubError, parse_repo, verify_signature
from evomind.llm.recommend import RecommendationError, generate_recommendation
from evomind.ml.rolling_origin import run_rolling_origin_evaluation
from evomind.ml.train import FEATURE_COLUMNS
from evomind.pipeline import PipelineResult, run_pipeline
from evomind.pr_risk import build_pr_report, render_comment, report_to_dict

load_dotenv()

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _validate_repo_arg(repo: str) -> None:
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

_last_result: dict[str, PipelineResult] = {}

app = FastAPI(
    title="EvoMind API",
    description="AI-powered software evolution intelligence: predictive bug-proneness, "
    "technical debt signals, and risk scoring from Git history and code metrics.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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


class RiskReason(BaseModel):
    feature: str
    label: str
    value: float
    percentile: float
    impact: float


class TrendPoint(BaseModel):
    date: str
    risk: float | None


class RiskyFile(BaseModel):
    file_path: str
    risk_score: float
    reasons: list[RiskReason] = []
    trend: list[TrendPoint] = []
    trend_delta: float | None = None


class CoupledFile(BaseModel):
    file_path: str
    afferent: int
    efferent: int
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
    feature_importance_kind: str = ""
    top_risk_files: list[RiskyFile]
    dependency_edge_count: int
    most_coupled_files: list[CoupledFile]
    cyclic_groups: list[list[str]]
    llm_szz_assessed: int | None = None
    llm_szz_fallback: int | None = None


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
    summary: dict[str, dict[str, float]]


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
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


def _finite_or_none(value):
    if value is None:
        return None
    value = float(value)
    return value if value == value else None


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
            RiskyFile(
                file_path=row.file_path,
                risk_score=row.risk_score,
                reasons=[RiskReason(**vars(r)) for r in getattr(row, "reasons", None) or []],
                trend=[TrendPoint(**vars(t)) for t in getattr(row, "trend", None) or []],
                trend_delta=_finite_or_none(getattr(row, "trend_delta", None)),
            )
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

    _last_result.clear()
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
            except Exception as exc:
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
            except Exception as exc:
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


ANALYSIS_TTL_SECONDS = 6 * 60 * 60
PR_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}
_analysis_cache: dict[str, tuple[float, PipelineResult]] = {}
_analysis_lock = threading.Lock()
_webhook_log: deque = deque(maxlen=20)


def _canonical(repo: str) -> str:
    owner, name = parse_repo(repo)
    return f"https://github.com/{owner}/{name}".lower()


def _analysis_for(repo: str) -> PipelineResult:
    key = _canonical(repo)
    with _analysis_lock:
        for cached_repo, result in _last_result.items():
            try:
                if _canonical(cached_repo) == key:
                    return result
            except ValueError:
                continue
        hit = _analysis_cache.get(key)
        if hit and time.time() - hit[0] < ANALYSIS_TTL_SECONDS:
            return hit[1]
        owner, name = parse_repo(repo)
        result = run_pipeline(f"https://github.com/{owner}/{name}")
        _analysis_cache[key] = (time.time(), result)
        return result


def _check_pull_request(repo: str, number: int, post_comment: bool) -> dict:
    owner, name = parse_repo(repo)
    client = GitHubClient(os.environ.get("GITHUB_TOKEN"))
    changed = client.pull_request_files(owner, name, number)
    report = build_pr_report(_analysis_for(repo), f"{owner}/{name}", number, changed)
    body = render_comment(report)
    comment_url = None
    if post_comment:
        comment_url = (client.upsert_comment(owner, name, number, body) or {}).get("html_url")
    return {**report_to_dict(report), "comment_markdown": body, "comment_url": comment_url}


class PRRiskRequest(BaseModel):
    repo: str = Field(..., description="GitHub repository URL, e.g. https://github.com/pallets/click")
    pr_number: int = Field(..., ge=1)
    post_comment: bool = Field(False, description="Post or update the report as a PR comment (needs GITHUB_TOKEN)")


@app.post("/pr-risk")
def pr_risk(req: PRRiskRequest) -> dict:
    try:
        return _check_pull_request(req.repo, req.pr_number, req.post_comment)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GitHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _run_webhook_check(repo: str, number: int) -> None:
    started = time.time()
    try:
        outcome = _check_pull_request(repo, number, post_comment=True)
        status = f"commented ({outcome['high_risk_count']} high-risk files)"
    except Exception as exc:
        status = f"failed: {exc}"
    _webhook_log.appendleft({"repo": repo, "pr": number, "status": status,
                             "seconds": round(time.time() - started, 1), "at": time.strftime("%Y-%m-%d %H:%M:%S")})


@app.post("/webhook/github", status_code=202)
async def github_webhook(request: Request, background: BackgroundTasks) -> dict:
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook disabled: set GITHUB_WEBHOOK_SECRET on the server.")
    body = await request.body()
    if not verify_signature(secret, body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return {"status": "pong"}
    if event != "pull_request":
        return {"status": "ignored", "reason": f"event '{event}' is not handled"}

    payload = json.loads(body)
    action = payload.get("action")
    if action not in PR_ACTIONS:
        return {"status": "ignored", "reason": f"action '{action}' does not change the code"}

    repo = payload["repository"]["html_url"]
    number = payload["pull_request"]["number"]
    background.add_task(_run_webhook_check, repo, number)
    return {"status": "accepted", "repo": repo, "pr": number}


@app.get("/webhook/github/recent")
def github_webhook_recent() -> list:
    return list(_webhook_log)
