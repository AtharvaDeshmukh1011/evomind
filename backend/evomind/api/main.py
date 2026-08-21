"""EvoMind API: analyze a Git repository and return software evolution risk data."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    try:
        result = run_pipeline(
            repo=req.repo,
            horizon_days=req.horizon_days,
            train_fraction=req.train_fraction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _last_result.clear()  # single-demo cache: only ever keep the latest analysis
    _last_result[req.repo] = result

    top_risk = result.file_risk_scores.head(req.top_n)

    most_coupled = sorted(
        result.coupling, key=lambda c: c.afferent + c.efferent, reverse=True
    )[:req.top_n]

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
