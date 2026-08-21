from evomind.metrics.code_metrics import SUPPORTED_EXTENSIONS, compute_file_metrics

SIMPLE_SOURCE = """
def add(a, b):
    return a + b


def branchy(x):
    if x > 0:
        return 1
    elif x < 0:
        return -1
    else:
        return 0
"""

JS_SOURCE = """
function add(a, b) {
    return a + b;
}

function branchy(x) {
    if (x > 0) {
        return 1;
    } else if (x < 0) {
        return -1;
    } else {
        return 0;
    }
}
"""


def test_compute_file_metrics_basic():
    m = compute_file_metrics("sample.py", SIMPLE_SOURCE)
    assert m is not None
    assert m.function_count == 2
    assert m.max_cyclomatic_complexity >= 2
    assert m.loc > 0
    assert m.maintainability_index > 0


def test_compute_file_metrics_rejects_invalid_syntax():
    assert compute_file_metrics("broken.py", "def broken(:\n    pass") is None


def test_compute_file_metrics_javascript():
    m = compute_file_metrics("sample.js", JS_SOURCE)
    assert m is not None
    assert m.function_count == 2
    assert m.max_cyclomatic_complexity >= 3  # branchy has 3 branches
    assert m.loc > 0
    # lizard doesn't compute these — explicit zero, not a silently wrong number
    assert m.maintainability_index == 0.0
    assert m.halstead_volume == 0.0


def test_compute_file_metrics_unsupported_extension_returns_none():
    assert compute_file_metrics("data.bin", "whatever") is None


def test_supported_extensions_includes_common_languages():
    for ext in (".py", ".js", ".ts", ".java", ".go", ".rb", ".c", ".cpp", ".cs", ".php"):
        assert ext in SUPPORTED_EXTENSIONS
