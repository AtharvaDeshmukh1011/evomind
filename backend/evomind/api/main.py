"""EvoMind API: analyze a Git repository and return software evolution risk data."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from evomind.pipeline import run_pipeline

STATIC_DIR = Path(__file__).resolve().parent / "static"

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

    top_risk = result.file_risk_scores.head(req.top_n)

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
    )
