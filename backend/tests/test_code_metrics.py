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
    assert m.max_cyclomatic_complexity >= 3
    assert m.loc > 0
    assert m.maintainability_index == 0.0
    assert m.halstead_volume == 0.0


def test_compute_file_metrics_unsupported_extension_returns_none():
    assert compute_file_metrics("data.bin", "whatever") is None


def test_supported_extensions_includes_common_languages():
    for ext in (".py", ".js", ".ts", ".java", ".go", ".rb", ".c", ".cpp", ".cs", ".php"):
        assert ext in SUPPORTED_EXTENSIONS


DART_SOURCE = """
class RequestModel {
  final String url;
  RequestModel(this.url);

  String describe(int retries, bool secure) {
    if (url.isEmpty) {
      return "empty";
    } else if (secure && url.startsWith("http:")) {
      return "insecure";
    }
    var out = "";
    for (var i = 0; i < retries; i++) {
      out += i.isEven ? "a" : "b";
    }
    return out;
  }

  int code(String m) {
    try {
      switch (m) {
        case "GET": return 1;
        case "POST": return 2;
      }
    } catch (e) {
      return -1;
    }
    return 0;
  }
}
"""


def _dart_cc(body):
    return compute_file_metrics("lib/x.dart", f"class A {{ {body} }}").max_cyclomatic_complexity


def test_dart_bodiless_constructor_is_not_a_function_like_java():
    assert compute_file_metrics("r.dart", "class R { final String u; R(this.u); }").function_count == 0
    assert compute_file_metrics("r.dart", "class R { final String u; R(this.u) { print(u); } }").function_count == 1


def test_dart_is_supported():
    assert ".dart" in SUPPORTED_EXTENSIONS


def test_dart_counts_real_branches_exactly():
    m = compute_file_metrics("lib/request_model.dart", DART_SOURCE)
    assert m is not None
    assert m.function_count == 2
    assert m.max_cyclomatic_complexity == 6
    assert m.file_path == "lib/request_model.dart"
    assert m.loc == DART_SOURCE.count("\n") + 1


def test_dart_nullable_types_are_not_branches():
    assert _dart_cc("String? f(Map<String, int?>? m, List<int?>? xs) { return null; }") == 1


def test_dart_safe_calls_are_not_branches():
    assert _dart_cc('int? f(String? a, List<int>? xs) { return a?.length ?? xs?[0]; }') == 2


def test_dart_null_coalescing_counts_once_like_or():
    assert _dart_cc('String f(String? a) { return a ?? "x"; }') == 2
    assert _dart_cc('void f(String? a) { a ??= "x"; }') == 2


def test_dart_ternary_is_still_a_branch():
    assert _dart_cc("String? f(bool ok, String? a) { return ok ? a : null; }") == 2
