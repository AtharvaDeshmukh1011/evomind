from __future__ import annotations

import math
from dataclasses import dataclass, field

from evomind.integrations.github import COMMENT_MARKER, ChangedFile
from evomind.metrics.code_metrics import SUPPORTED_EXTENSIONS

BANDS = ((0.66, "Critical", "🔴"), (0.50, "Serious", "🟠"), (0.33, "Watch", "🟡"), (0.0, "Low", "🟢"))
HIGH_RISK = 0.50
MAX_ROWS = 25


@dataclass
class PRFileRisk:
    path: str
    status: str
    risk_score: float | None = None
    band: str = ""
    reasons: list = field(default_factory=list)
    trend_delta: float | None = None
    note: str = ""


@dataclass
class PRReport:
    repo: str
    number: int
    files: list[PRFileRisk]
    model_name: str
    roc_auc: float | None
    horizon_days: int

    @property
    def scored(self) -> list[PRFileRisk]:
        return [f for f in self.files if f.risk_score is not None]

    @property
    def high_risk(self) -> list[PRFileRisk]:
        return [f for f in self.scored if f.risk_score >= HIGH_RISK]

    @property
    def max_risk(self) -> float | None:
        return max((f.risk_score for f in self.scored), default=None)


def band_for(score: float) -> tuple[str, str]:
    for floor, name, icon in BANDS:
        if score >= floor:
            return name, icon
    return BANDS[-1][1], BANDS[-1][2]


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def _clean(value):
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else value


def build_pr_report(result, repo: str, number: int, changed: list[ChangedFile]) -> PRReport:
    rows = {}
    for row in result.file_risk_scores.itertuples():
        rows[_norm(row.file_path)] = row

    files = []
    for change in changed:
        path = _norm(change.path)
        entry = PRFileRisk(path=path, status=change.status)
        if change.status == "removed":
            entry.note = "removed in this PR"
        else:
            row = rows.get(path) or (rows.get(_norm(change.previous_path)) if change.previous_path else None)
            if row is not None:
                entry.risk_score = float(row.risk_score)
                entry.band = band_for(entry.risk_score)[0]
                entry.reasons = list(getattr(row, "reasons", None) or [])
                entry.trend_delta = _clean(getattr(row, "trend_delta", None))
            elif not path.endswith(SUPPORTED_EXTENSIONS):
                entry.note = "not analysed (file type not supported)"
            elif change.status == "added":
                entry.note = "new file — no history yet"
            else:
                entry.note = "no history in the analysed revision"
        files.append(entry)

    files.sort(key=lambda f: (f.risk_score is None, -(f.risk_score or 0), f.path))

    report = result.training_report
    best = next((r for r in report.results if r.model_name == report.best_model_name), None)
    return PRReport(
        repo=repo,
        number=number,
        files=files,
        model_name=report.best_model_name,
        roc_auc=_clean(best.roc_auc) if best else None,
        horizon_days=result.horizon_days,
    )


def _why(reasons) -> str:
    parts = []
    for r in reasons[:2]:
        top = max(1, round((1 - r.percentile) * 100))
        value = f"{int(r.value):,}" if float(r.value).is_integer() else f"{r.value:.1f}"
        parts.append(f"{r.label} {value} (top {top}%)")
    return ", ".join(parts) or "—"


def _trend(delta) -> str:
    if delta is None:
        return "—"
    if delta > 0.02:
        return f"▲ +{delta:.2f}"
    if delta < -0.02:
        return f"▼ −{abs(delta):.2f}"
    return "steady"


def render_comment(report: PRReport) -> str:
    high = report.high_risk
    if high:
        noun = "file" if len(high) == 1 else "files"
        headline = f"This PR touches **{len(high)} high-risk {noun}** (Serious or above) — worth a careful review."
    elif report.scored:
        headline = "No high-risk files touched. ✅"
    else:
        headline = "None of the changed files could be scored."

    lines = [COMMENT_MARKER, "### EvoMind risk check", "", headline, ""]
    shown = report.files[:MAX_ROWS]
    if any(f.risk_score is not None for f in shown):
        lines += ["| File | Risk | Trend | Why |", "|---|---|---|---|"]
        for f in shown:
            if f.risk_score is None:
                continue
            name, icon = band_for(f.risk_score)
            lines.append(f"| `{f.path}` | {icon} {f.risk_score:.2f} {name} | {_trend(f.trend_delta)} | {_why(f.reasons)} |")
    unscored = [f for f in shown if f.risk_score is None]
    if unscored:
        lines += ["", "<details><summary>Not scored</summary>", ""]
        lines += [f"- `{f.path}` — {f.note}" for f in unscored]
        lines += ["", "</details>"]
    if len(report.files) > MAX_ROWS:
        lines += ["", f"…and {len(report.files) - MAX_ROWS} more changed files."]

    auc = f" · ROC-AUC {report.roc_auc:.2f}" if report.roc_auc is not None else ""
    lines += [
        "",
        f"<sub>Risk = predicted probability that a file needs a bug fix within {report.horizon_days} days, "
        f"from its version-control history and code metrics. Model: {report.model_name}{auc}. "
        "A prioritisation signal, not a verdict.</sub>",
    ]
    return "\n".join(lines)


def report_to_dict(report: PRReport) -> dict:
    return {
        "repo": report.repo,
        "number": report.number,
        "high_risk_count": len(report.high_risk),
        "max_risk": report.max_risk,
        "model_name": report.model_name,
        "roc_auc": report.roc_auc,
        "files": [
            {
                "path": f.path,
                "status": f.status,
                "risk_score": f.risk_score,
                "band": f.band,
                "trend_delta": f.trend_delta,
                "note": f.note,
                "reasons": [vars(r) for r in f.reasons],
            }
            for f in report.files
        ],
    }
