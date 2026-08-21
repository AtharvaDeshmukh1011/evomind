"""Intra-repo Python dependency graph, coupling metrics, and cycle detection.

Imports are parsed with the stdlib `ast` module and resolved to file paths
purely within the mined snapshot — stdlib and third-party imports never
match an internal module name, so they're silently dropped rather than
producing external nodes. This keeps the graph scoped to "what this repo's
own files depend on," which is what coupling/cycle analysis actually needs.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field


def _path_to_module(file_path: str) -> str:
    """Converts a repo-relative file path to a dotted module name.

    e.g. "src/flask/app.py" -> "flask.app" (a leading src/ or lib/ container
    directory is stripped, matching common layout conventions),
    "flask/__init__.py" -> "flask".
    """
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
    """The parent package of a dotted module name, or "" for a top-level module."""
    return module.rsplit(".", 1)[0] if "." in module else ""


def _extract_imported_modules(source: str, current_module: str) -> set[str]:
    """Parses one file's AST and returns the dotted module names it imports."""
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
                # Relative import: walk up (level - 1) packages from the
                # current module's own package before appending node.module.
                base_parts = current_package.split(".") if current_package else []
                up = node.level - 1
                base_parts = base_parts[: len(base_parts) - up] if up else base_parts
                base = ".".join(base_parts)
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            if target:
                modules.add(target)
                # `from a.b import c` — c might itself be a submodule, not
                # just a name, so register that possibility too.
                for alias in node.names:
                    modules.add(f"{target}.{alias.name}")

    return modules


@dataclass
class ImportEdge:
    source: str  # importing file
    target: str  # imported file


@dataclass
class DependencyGraph:
    files: list[str] = field(default_factory=list)
    edges: list[ImportEdge] = field(default_factory=list)


def build_dependency_graph(snapshots: dict[str, str]) -> DependencyGraph:
    """Builds a graph of import edges restricted to files present in `snapshots`."""
    # Python-only: other languages mined alongside .py files (see
    # SUPPORTED_EXTENSIONS in code_metrics.py) are excluded here rather than
    # AST-parsed as if they were Python source.
    py_snapshots = {path: src for path, src in snapshots.items() if path.endswith(".py")}

    module_to_file = {_path_to_module(path): path for path in py_snapshots if _path_to_module(path)}
    module_names = set(module_to_file)

    graph = DependencyGraph(files=list(py_snapshots))

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

        for target_file in matched_targets:
            graph.edges.append(ImportEdge(source=file_path, target=target_file))

    return graph


@dataclass
class CouplingMetrics:
    file_path: str
    afferent: int  # Ca — files that import this one
    efferent: int  # Ce — files this one imports
    instability: float  # Ce / (Ce + Ca); 0.0 for an isolated file


def compute_coupling(graph: DependencyGraph) -> list[CouplingMetrics]:
    """Afferent/efferent coupling and instability (Robert C. Martin's I metric) per file."""
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
    """Strongly connected components of size > 1 — genuine circular dependency
    clusters (mutual reachability), not just linear import chains.

    Implemented as Tarjan's algorithm.
    """
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
