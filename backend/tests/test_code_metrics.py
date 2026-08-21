from evomind.metrics.code_metrics import compute_file_metrics

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


def test_compute_file_metrics_basic():
    m = compute_file_metrics("sample.py", SIMPLE_SOURCE)
    assert m is not None
    assert m.function_count == 2
    assert m.max_cyclomatic_complexity >= 2
    assert m.loc > 0
    assert m.maintainability_index > 0


def test_compute_file_metrics_rejects_invalid_syntax():
    assert compute_file_metrics("broken.py", "def broken(:\n    pass") is None
