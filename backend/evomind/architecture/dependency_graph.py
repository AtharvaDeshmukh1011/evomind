from __future__ import annotations

import ast
import os
import posixpath
import re
from dataclasses import dataclass, field

JS_TS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")


def _path_to_module(file_path: str) -> str:
    parts = file_path.replace("\\", "/").split("/")
    if parts and parts[0] in ("src", "lib"):
        parts = parts[1:]
    if not parts or not parts[-1]:
        return ""
    last = parts[-1]
    if last == "__init__.py":
        parts = parts[:-1]
    elif last.endswith(".py"):
        parts[-1] = last[:-3]
    else:
        return ""
    return ".".join(p for p in parts if p)


def _package_of(module: str) -> str:
    return module.rsplit(".", 1)[0] if "." in module else ""


def _extract_imported_modules(source: str, current_module: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    modules: set[str] = set()
    current_package = _package_of(current_module)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                base_parts = current_package.split(".") if current_package else []
                up = node.level - 1
                base_parts = base_parts[: len(base_parts) - up] if up else base_parts
                base = ".".join(base_parts)
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            if target:
                modules.add(target)
                for alias in node.names:
                    modules.add(f"{target}.{alias.name}")

    return modules


_JS_IMPORT_PATTERN = re.compile(
    r"""(?:\bfrom\s+|\brequire\(\s*|\bimport\(\s*)['"]([^'"]+)['"]"""
)
_JS_SIDE_EFFECT_IMPORT_PATTERN = re.compile(r"""^\s*import\s+['"]([^'"]+)['"]""", re.MULTILINE)


def _extract_js_imports(source: str) -> set[str]:
    specifiers = set(_JS_IMPORT_PATTERN.findall(source))
    specifiers.update(_JS_SIDE_EFFECT_IMPORT_PATTERN.findall(source))
    return specifiers


def _resolve_js_import(current_file: str, specifier: str, path_lookup: dict[str, str]) -> str | None:
    if not specifier.startswith("."):
        return None

    current_dir = posixpath.dirname(current_file.replace(os.sep, "/"))
    resolved_base = posixpath.normpath(posixpath.join(current_dir, specifier))

    candidates = [resolved_base]
    if not resolved_base.endswith(JS_TS_EXTENSIONS):
        candidates += [resolved_base + ext for ext in JS_TS_EXTENSIONS]
        candidates += [f"{resolved_base}/index{ext}" for ext in JS_TS_EXTENSIONS]

    for candidate in candidates:
        if candidate in path_lookup:
            return path_lookup[candidate]
    return None


_JAVA_PACKAGE_PATTERN = re.compile(r"\bpackage\s+([\w.]+)\s*;")
_JAVA_IMPORT_PATTERN = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)(\.\*)?\s*;", re.MULTILINE)


def _java_class_name(file_path: str) -> str:
    name = file_path.replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-5] if name.endswith(".java") else name


def _java_full_class_name(file_path: str, source: str) -> str:
    match = _JAVA_PACKAGE_PATTERN.search(source)
    class_name = _java_class_name(file_path)
    return f"{match.group(1)}.{class_name}" if match else class_name


def _extract_java_imports(source: str) -> set[tuple[str, bool]]:
    return {(m.group(1), bool(m.group(2))) for m in _JAVA_IMPORT_PATTERN.finditer(source)}


@dataclass
class ImportEdge:
    source: str
    target: str


@dataclass
class DependencyGraph:
    files: list[str] = field(default_factory=list)
    edges: list[ImportEdge] = field(default_factory=list)


def _build_python_edges(py_snapshots: dict[str, str]) -> list[ImportEdge]:
    module_to_file = {_path_to_module(path): path for path in py_snapshots if _path_to_module(path)}
    module_names = set(module_to_file)

    edges: list[ImportEdge] = []
    for file_path, source in py_snapshots.items():
        current_module = _path_to_module(file_path)
        imported = _extract_imported_modules(source, current_module)

        matched_targets: set[str] = set()
        for mod in imported:
            candidate = mod
            while candidate:
                if candidate in module_names and candidate != current_module:
                    matched_targets.add(module_to_file[candidate])
                    break
                candidate = _package_of(candidate)

        edges.extend(ImportEdge(source=file_path, target=t) for t in matched_targets)
    return edges


def _build_js_edges(js_snapshots: dict[str, str]) -> list[ImportEdge]:
    path_lookup = {path.replace(os.sep, "/"): path for path in js_snapshots}

    edges: list[ImportEdge] = []
    for file_path, source in js_snapshots.items():
        matched_targets: set[str] = set()
        for spec in _extract_js_imports(source):
            target = _resolve_js_import(file_path, spec, path_lookup)
            if target and target != file_path:
                matched_targets.add(target)

        edges.extend(ImportEdge(source=file_path, target=t) for t in matched_targets)
    return edges


def _build_java_edges(java_snapshots: dict[str, str]) -> list[ImportEdge]:
    full_name_to_file = {_java_full_class_name(path, src): path for path, src in java_snapshots.items()}

    files_by_package: dict[str, list[str]] = {}
    for full_name, path in full_name_to_file.items():
        files_by_package.setdefault(_package_of(full_name), []).append(path)

    edges: list[ImportEdge] = []
    for file_path, source in java_snapshots.items():
        current_name = _java_full_class_name(file_path, source)
        matched_targets: set[str] = set()

        for dotted_name, is_wildcard in _extract_java_imports(source):
            if is_wildcard:
                matched_targets.update(
                    p for p in files_by_package.get(dotted_name, []) if p != file_path
                )
            elif dotted_name in full_name_to_file and dotted_name != current_name:
                matched_targets.add(full_name_to_file[dotted_name])

        edges.extend(ImportEdge(source=file_path, target=t) for t in matched_targets)
    return edges


def build_dependency_graph(snapshots: dict[str, str]) -> DependencyGraph:
    py_snapshots = {path: src for path, src in snapshots.items() if path.endswith(".py")}
    js_snapshots = {path: src for path, src in snapshots.items() if path.endswith(JS_TS_EXTENSIONS)}
    java_snapshots = {path: src for path, src in snapshots.items() if path.endswith(".java")}

    graph = DependencyGraph(files=[*py_snapshots, *js_snapshots, *java_snapshots])
    graph.edges = (
        _build_python_edges(py_snapshots)
        + _build_js_edges(js_snapshots)
        + _build_java_edges(java_snapshots)
    )
    return graph


@dataclass
class CouplingMetrics:
    file_path: str
    afferent: int
    efferent: int
    instability: float


def compute_coupling(graph: DependencyGraph) -> list[CouplingMetrics]:
    efferent: dict[str, set[str]] = {f: set() for f in graph.files}
    afferent: dict[str, set[str]] = {f: set() for f in graph.files}

    for edge in graph.edges:
        efferent[edge.source].add(edge.target)
        afferent[edge.target].add(edge.source)

    results = []
    for f in graph.files:
        ce, ca = len(efferent[f]), len(afferent[f])
        instability = ce / (ce + ca) if (ce + ca) else 0.0
        results.append(CouplingMetrics(file_path=f, afferent=ca, efferent=ce, instability=instability))
    return results


def find_cyclic_groups(graph: DependencyGraph) -> list[list[str]]:
    adjacency: dict[str, list[str]] = {f: [] for f in graph.files}
    for edge in graph.edges:
        adjacency[edge.source].append(edge.target)

    index_counter = [0]
    stack: list[str] = []
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        index[node] = index_counter[0]
        lowlink[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack[node] = True

        for neighbor in adjacency.get(node, ()):
            if neighbor not in index:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif on_stack.get(neighbor):
                lowlink[node] = min(lowlink[node], index[neighbor])

        if lowlink[node] == index[node]:
            component = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                component.append(w)
                if w == node:
                    break
            if len(component) > 1:
                components.append(component)

    for f in graph.files:
        if f not in index:
            strongconnect(f)

    return components
