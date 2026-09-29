from __future__ import annotations

import re
from dataclasses import dataclass, replace

import lizard
from radon.complexity import cc_visit
from radon.metrics import h_visit, mi_visit
from radon.raw import analyze

LIZARD_EXTENSIONS: frozenset[str] = frozenset(
    f".{ext}" for lang in lizard.languages() for ext in lang.ext
)
SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(sorted(LIZARD_EXTENSIONS | {".py", ".dart"}))

_DART_NULL_SAFETY: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\?\?="), "||"),
    (re.compile(r"\?\?"), "||"),
    (re.compile(r"\?(?=[.\[])"), ""),
    (re.compile(r"(?<=[\w>\]])\?"), ""),
)


@dataclass
class FileMetrics:
    file_path: str
    loc: int
    lloc: int
    sloc: int
    comment_lines: int
    blank_lines: int
    avg_cyclomatic_complexity: float
    max_cyclomatic_complexity: int
    function_count: int
    maintainability_index: float
    halstead_volume: float
    halstead_difficulty: float


def _compute_python_metrics(file_path: str, source: str) -> FileMetrics | None:
    try:
        raw = analyze(source)
        blocks = cc_visit(source)
        mi = mi_visit(source, multi=True)
        halstead = h_visit(source)
    except SyntaxError:
        return None

    complexities = [b.complexity for b in blocks]
    total = halstead.total

    return FileMetrics(
        file_path=file_path,
        loc=raw.loc,
        lloc=raw.lloc,
        sloc=raw.sloc,
        comment_lines=raw.comments,
        blank_lines=raw.blank,
        avg_cyclomatic_complexity=(sum(complexities) / len(complexities)) if complexities else 0.0,
        max_cyclomatic_complexity=max(complexities) if complexities else 0,
        function_count=len(blocks),
        maintainability_index=mi,
        halstead_volume=total.volume,
        halstead_difficulty=total.difficulty,
    )


def _compute_lizard_metrics(file_path: str, source: str) -> FileMetrics | None:
    info = lizard.analyze_file.analyze_source_code(file_path, source)
    complexities = [f.cyclomatic_complexity for f in info.function_list]
    total_lines = source.count("\n") + 1

    return FileMetrics(
        file_path=file_path,
        loc=total_lines,
        lloc=info.nloc,
        sloc=info.nloc,
        comment_lines=0,
        blank_lines=0,
        avg_cyclomatic_complexity=info.average_cyclomatic_complexity,
        max_cyclomatic_complexity=max(complexities) if complexities else 0,
        function_count=len(info.function_list),
        maintainability_index=0.0,
        halstead_volume=0.0,
        halstead_difficulty=0.0,
    )


def neutralise_dart_null_safety(source: str) -> str:
    for pattern, replacement in _DART_NULL_SAFETY:
        source = pattern.sub(replacement, source)
    return source


def _compute_dart_metrics(file_path: str, source: str) -> FileMetrics | None:
    measured = _compute_lizard_metrics(
        file_path[: -len(".dart")] + ".java", neutralise_dart_null_safety(source)
    )
    return replace(measured, file_path=file_path) if measured else None


def compute_file_metrics(file_path: str, source: str) -> FileMetrics | None:
    if file_path.endswith(".py"):
        return _compute_python_metrics(file_path, source)
    if file_path.endswith(".dart"):
        return _compute_dart_metrics(file_path, source)
    if file_path.endswith(tuple(LIZARD_EXTENSIONS)):
        return _compute_lizard_metrics(file_path, source)
    return None
