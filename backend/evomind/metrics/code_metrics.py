"""Static code metrics for a source file — Python via radon, other languages via lizard.

Python gets the richer radon-based analysis (adds maintainability index and
Halstead metrics on top of complexity/LOC, at the cost of being Python-only —
it parses a real AST). Every other language lizard supports gets complexity
and LOC via its heuristic tokenizer; maintainability index and Halstead
metrics are defaulted to 0.0 for those files since lizard doesn't compute
them — an honest gap, not a silently wrong number.
"""

from __future__ import annotations

from dataclasses import dataclass

import lizard
from radon.complexity import cc_visit
from radon.metrics import h_visit, mi_visit
from radon.raw import analyze

# Every extension lizard has a language plugin for, plus Python (handled by
# radon instead, below). Built from lizard's own language registry rather
# than a hand-maintained list, so new lizard languages are picked up for
# free.
LIZARD_EXTENSIONS: frozenset[str] = frozenset(
    f".{ext}" for lang in lizard.languages() for ext in lang.ext
)
SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(sorted(LIZARD_EXTENSIONS | {".py"}))


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
    """Returns None if the file cannot be parsed as valid Python."""
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
    """Complexity/LOC for any lizard-supported non-Python language.

    lizard's tokenizer is heuristic rather than a real parser, so it doesn't
    raise on malformed input — there's no equivalent to radon's SyntaxError
    rejection here, just whatever best-effort numbers it can extract.
    """
    info = lizard.analyze_file.analyze_source_code(file_path, source)
    complexities = [f.cyclomatic_complexity for f in info.function_list]
    total_lines = source.count("\n") + 1

    return FileMetrics(
        file_path=file_path,
        loc=total_lines,
        lloc=info.nloc,
        sloc=info.nloc,
        comment_lines=0,  # not distinguished from blanks by lizard's aggregate stats
        blank_lines=0,
        avg_cyclomatic_complexity=info.average_cyclomatic_complexity,
        max_cyclomatic_complexity=max(complexities) if complexities else 0,
        function_count=len(info.function_list),
        maintainability_index=0.0,  # lizard doesn't compute this
        halstead_volume=0.0,
        halstead_difficulty=0.0,
    )


def compute_file_metrics(file_path: str, source: str) -> FileMetrics | None:
    """Computes static code metrics for one file, dispatched by extension.

    Returns None for a file whose extension isn't supported at all, or (for
    Python) whose source doesn't parse.
    """
    if file_path.endswith(".py"):
        return _compute_python_metrics(file_path, source)
    if file_path.endswith(tuple(LIZARD_EXTENSIONS)):
        return _compute_lizard_metrics(file_path, source)
    return None
