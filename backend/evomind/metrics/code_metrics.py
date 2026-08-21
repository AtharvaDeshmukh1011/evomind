"""Static code metrics for a single Python source file, via radon."""

from __future__ import annotations

from dataclasses import dataclass

from radon.complexity import cc_visit
from radon.metrics import h_visit, mi_visit
from radon.raw import analyze


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


def compute_file_metrics(file_path: str, source: str) -> FileMetrics | None:
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
