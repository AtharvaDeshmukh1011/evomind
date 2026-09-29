from evomind.architecture.dependency_graph import (
    build_dependency_graph,
    compute_coupling,
    find_cyclic_groups,
)


def test_absolute_import_creates_edge():
    snapshots = {
        "pkg/a.py": "import pkg.b\n",
        "pkg/b.py": "x = 1\n",
        "pkg/__init__.py": "",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("pkg/a.py", "pkg/b.py") in edges


def test_from_import_creates_edge():
    snapshots = {
        "pkg/a.py": "from pkg.b import thing\n",
        "pkg/b.py": "thing = 1\n",
        "pkg/__init__.py": "",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("pkg/a.py", "pkg/b.py") in edges


def test_relative_import_creates_edge():
    snapshots = {
        "pkg/sub/a.py": "from .. import b\n",
        "pkg/b.py": "x = 1\n",
        "pkg/__init__.py": "",
        "pkg/sub/__init__.py": "",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("pkg/sub/a.py", "pkg/b.py") in edges


def test_external_import_produces_no_edge():
    snapshots = {"pkg/a.py": "import os\nimport requests\n"}
    graph = build_dependency_graph(snapshots)
    assert graph.edges == []


def test_self_import_ignored():
    snapshots = {"pkg/a.py": "import pkg.a\n"}
    graph = build_dependency_graph(snapshots)
    assert graph.edges == []


def test_coupling_metrics_afferent_efferent_instability():
    snapshots = {
        "pkg/a.py": "import pkg.b\n",
        "pkg/b.py": "x = 1\n",
        "pkg/__init__.py": "",
    }
    graph = build_dependency_graph(snapshots)
    metrics = {m.file_path: m for m in compute_coupling(graph)}

    assert metrics["pkg/a.py"].efferent == 1
    assert metrics["pkg/a.py"].afferent == 0
    assert metrics["pkg/a.py"].instability == 1.0

    assert metrics["pkg/b.py"].efferent == 0
    assert metrics["pkg/b.py"].afferent == 1
    assert metrics["pkg/b.py"].instability == 0.0


def test_isolated_file_has_zero_instability():
    snapshots = {"pkg/lonely.py": "x = 1\n"}
    graph = build_dependency_graph(snapshots)
    metrics = compute_coupling(graph)
    assert metrics[0].instability == 0.0


def test_two_file_cycle_detected():
    snapshots = {
        "pkg/a.py": "import pkg.b\n",
        "pkg/b.py": "import pkg.a\n",
        "pkg/__init__.py": "",
    }
    graph = build_dependency_graph(snapshots)
    cycles = find_cyclic_groups(graph)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"pkg/a.py", "pkg/b.py"}


def test_no_cycle_in_linear_chain():
    snapshots = {
        "pkg/a.py": "import pkg.b\n",
        "pkg/b.py": "import pkg.c\n",
        "pkg/c.py": "x = 1\n",
        "pkg/__init__.py": "",
    }
    graph = build_dependency_graph(snapshots)
    assert find_cyclic_groups(graph) == []


def test_js_relative_import_with_extension_resolves():
    snapshots = {
        "src/a.js": "import b from './b';\n",
        "src/b.js": "export default 1;\n",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("src/a.js", "src/b.js") in edges


def test_js_named_import_resolves():
    snapshots = {
        "src/a.js": "import { thing } from './b';\n",
        "src/b.js": "export const thing = 1;\n",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("src/a.js", "src/b.js") in edges


def test_js_require_resolves():
    snapshots = {
        "src/a.js": "const b = require('./b');\n",
        "src/b.js": "module.exports = 1;\n",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("src/a.js", "src/b.js") in edges


def test_js_dynamic_import_resolves():
    snapshots = {
        "src/a.js": "const b = await import('./b');\n",
        "src/b.js": "export default 1;\n",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("src/a.js", "src/b.js") in edges


def test_js_side_effect_import_resolves():
    snapshots = {
        "src/a.js": "import './polyfill';\n",
        "src/polyfill.js": "window.x = 1;\n",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("src/a.js", "src/polyfill.js") in edges


def test_js_index_file_resolves():
    snapshots = {
        "src/a.js": "import utils from './utils';\n",
        "src/utils/index.js": "export default {};\n",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("src/a.js", "src/utils/index.js") in edges


def test_ts_extension_resolves_across_ts_and_tsx():
    snapshots = {
        "src/a.ts": "import Component from './Component';\n",
        "src/Component.tsx": "export default () => null;\n",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("src/a.ts", "src/Component.tsx") in edges


def test_js_parent_directory_import_resolves():
    snapshots = {
        "src/nested/a.js": "import b from '../b';\n",
        "src/b.js": "export default 1;\n",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("src/nested/a.js", "src/b.js") in edges


def test_js_bare_specifier_produces_no_edge():
    snapshots = {"src/a.js": "import _ from 'lodash';\n"}
    graph = build_dependency_graph(snapshots)
    assert graph.edges == []


def test_js_and_python_files_resolve_independently_in_same_graph():
    snapshots = {
        "src/a.js": "import b from './b';\n",
        "src/b.js": "export default 1;\n",
        "pkg/x.py": "import pkg.y\n",
        "pkg/y.py": "z = 1\n",
        "pkg/__init__.py": "",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("src/a.js", "src/b.js") in edges
    assert ("pkg/x.py", "pkg/y.py") in edges


def test_non_python_non_js_files_excluded_from_graph():
    snapshots = {"main.go": "package main\n"}
    graph = build_dependency_graph(snapshots)
    assert graph.files == []
    assert graph.edges == []


def test_java_import_creates_edge():
    snapshots = {
        "src/com/example/A.java": "package com.example;\nimport com.example.util.B;\nclass A {}\n",
        "src/com/example/util/B.java": "package com.example.util;\nclass B {}\n",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("src/com/example/A.java", "src/com/example/util/B.java") in edges


def test_java_wildcard_import_matches_all_classes_in_package():
    snapshots = {
        "A.java": "package com.example;\nimport com.example.util.*;\nclass A {}\n",
        "B.java": "package com.example.util;\nclass B {}\n",
        "C.java": "package com.example.util;\nclass C {}\n",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("A.java", "B.java") in edges
    assert ("A.java", "C.java") in edges


def test_java_default_package_resolves_by_bare_class_name():
    snapshots = {
        "A.java": "import B;\nclass A {}\n",
        "B.java": "class B {}\n",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("A.java", "B.java") in edges


def test_java_external_import_produces_no_edge():
    snapshots = {"A.java": "package com.example;\nimport java.util.List;\nclass A {}\n"}
    graph = build_dependency_graph(snapshots)
    assert graph.edges == []


def test_java_self_import_not_an_edge():
    snapshots = {"A.java": "package com.example;\nimport com.example.A;\nclass A {}\n"}
    graph = build_dependency_graph(snapshots)
    assert graph.edges == []


def test_java_python_js_all_resolve_independently():
    snapshots = {
        "A.java": "package p;\nimport p.util.B;\nclass A {}\n",
        "p/util/B.java": "package p.util;\nclass B {}\n",
        "src/a.js": "import b from './b';\n",
        "src/b.js": "export default 1;\n",
        "pkg/x.py": "import pkg.y\n",
        "pkg/y.py": "z = 1\n",
        "pkg/__init__.py": "",
    }
    graph = build_dependency_graph(snapshots)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("A.java", "p/util/B.java") in edges
    assert ("src/a.js", "src/b.js") in edges
    assert ("pkg/x.py", "pkg/y.py") in edges
