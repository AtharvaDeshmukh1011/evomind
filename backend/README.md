# EvoMind — Backend MVP

Predictive bug-proneness scoring from Git history and static code metrics,
architectural coupling/cycle analysis, and LLM-generated refactoring
recommendations for the riskiest files. This is the first working slice of
the full EvoMind proposal: it implements the **Version Control Analysis
Module**, **Source Code Analysis Module**, **Software Architecture Analysis
Module**, a real **Predictive Analytics Module**, and a first cut of the
**AI Recommendation Module**, end to end, on real repositories.

## What it actually does

1. Clones a repo once locally (`evomind/ingestion/repo_source.py`) and mines
   its full commit history for process metrics (`evomind/ingestion/git_miner.py`,
   via [PyDriller](https://pydriller.readthedocs.io/)).
2. Picks a **cutoff date** at `train_fraction` through the repo's history,
   and resolves the exact commit at or before it
   (`evomind/ingestion/tree_snapshot.py`, via `git rev-list`).
3. Reads the *exact* file tree at that commit — and separately at `HEAD` —
   via `git archive`, not by replaying commit diffs chronologically (see
   "Why tree reads, not diff replay" below).
4. Computes, per file, using only commits at or before the cutoff:
   process metrics (churn, commit count, author count, prior bug-fix count,
   age, recency) and static metrics (LOC, cyclomatic complexity, function
   count) on the file's content snapshot *as of the cutoff*
   (`evomind/metrics/code_metrics.py`). Python files get the fuller
   [radon](https://radon.readthedocs.io/)-based analysis (adds maintainability
   index and Halstead metrics, since it parses a real AST); every other
   language [lizard](https://github.com/terryyin/lizard) supports — JS/TS,
   Java, Go, Ruby, C/C++, C#, PHP, Rust, Kotlin, Swift, and more — gets
   complexity/LOC via its tokenizer, with maintainability index and Halstead
   metrics explicitly defaulted to 0.0 rather than guessed.
5. Labels each file `is_bug_prone = 1` if a bug-fixing commit (keyword
   heuristic on commit messages — see `BUG_KEYWORDS` in `git_miner.py`)
   touches it strictly *after* the cutoff, within `horizon_days`.
6. Trains a Random Forest against a Logistic Regression baseline
   (`evomind/ml/train.py`), evaluated on a held-out split with precision,
   recall, F1, ROC-AUC, and average precision.
7. Re-scores the repo's *current* files (latest snapshot) with the trained
   model to produce a live risk ranking.
8. Parses every current **Python and JS/TS** file's imports and builds an
   intra-repo dependency graph (`evomind/architecture/dependency_graph.py`),
   computing afferent/efferent coupling, instability, and circular-dependency
   groups (via Tarjan's SCC algorithm). Python imports are parsed with the
   stdlib `ast` module and resolved to dotted module names; JS/TS imports
   (`import`/`export ... from`, `require()`, dynamic `import()`) are
   extracted with a regex and resolved as relative file paths, the way
   Node/bundler resolution actually works. Either way, external packages and
   stdlib imports never match an internal file, so they're dropped rather
   than producing external nodes. Other languages are skipped entirely for
   this step (see limitations); such a repo shows an empty coupling panel
   rather than an error.
9. On request (dashboard button, or `POST /recommend`), sends one risky
   file's metrics + source excerpt to Claude (`evomind/llm/recommend.py`)
   and returns a structured summary + prioritized refactoring suggestions.

### Why tree reads, not diff replay

An earlier version reconstructed "current file content" by replaying every
commit's add/modify/delete/rename chronologically and mutating a shared
dict. This is unsound under non-linear history: a long-lived branch created
*before* a rename, merged *after* it, gets visited by PyDriller in
commit-date order — so a file already renamed away on the mainline gets
resurrected by that branch's later-dated (but logically earlier) commits.
This happened for real on Flask's history (`flask/app.py` → `src/flask/app.py`
in 2019, then reappearing because a pre-rename branch merged weeks later).
`git rev-list` + `git archive` sidestep it entirely by resolving one exact
commit and reading its tree directly — no diff replay, no ambiguity.
`tests/test_tree_snapshot.py` covers this.

### Why the cutoff/horizon split matters

Features only ever see commits at or before the cutoff; the label only ever
looks strictly after it. This is what keeps the evaluation honest — without
it, "predicting" bugs is trivial because the model can see the bug-fix
commit itself. `tests/test_feature_builder.py` has an explicit regression
test for this (`test_pre_cutoff_bug_fix_does_not_leak_into_label`).

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

For the "AI recommendation" button/`/recommend` endpoint, set an Anthropic
API key (the ML pipeline, dashboard, and `/analyze` all work fine without
one — this is only needed for LLM-generated refactoring suggestions):

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # PowerShell: $env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Without a key, `/recommend` fails with a clear 502 error message rather
than crashing — safe to leave unset while demoing the rest of the system.

## Run the pipeline from the CLI

```bash
.venv/Scripts/python.exe scripts/run_pipeline.py --repo https://github.com/pallets/flask
```

Prints held-out evaluation metrics, top feature importances, and the
current top-risk files, and saves `data/<name>_features.csv` and
`data/<name>_risk_scores.csv`.

Useful flags: `--horizon-days`, `--train-fraction`, `--out-name`, `--top-n`.
Works on any local path or public Git URL — swap `--repo` for whatever
you're demoing (a known repo is more convincing to an examiner than a toy
one).

## Run the API + dashboard

```bash
.venv/Scripts/python.exe -m uvicorn evomind.api.main:app --reload
```

Open `http://127.0.0.1:8000/` for the dashboard (repo input, model
evaluation, feature importances, live risk ranking, architectural coupling +
circular dependencies, "AI recommendation" button per file — light/dark).
Or call `POST /analyze` directly with `{"repo": "https://github.com/pallets/flask"}`,
then `POST /recommend` with `{"repo": "...", "file_path": "..."}` for one
file's suggestions. Interactive API docs at `http://127.0.0.1:8000/docs`.

**Expect roughly 1–3 minutes per analysis** — it walks the repo's full
commit history once (cloning it locally first so nothing is fetched twice).
Flask (~2000 commits, 94 files) takes about 90–150s; smaller repos are
faster. Don't run concurrent `/analyze` requests against the same server —
the underlying clone/mining is CPU- and I/O-heavy and multiple runs at once
will make all of them slower, not just share the wait.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests/ -v
```

## Known limitations (be upfront about these in the defense — it reads as rigor, not weakness)

- **Dependency graph / coupling analysis covers Python and JS/TS only.**
  Bug-proneness prediction (the core pipeline) works on any language lizard
  supports — validated end-to-end on real JS/TS repos (e.g. axios) with zero
  Python files, and the coupling panel now covers those too (also validated
  on axios: 305 real edges, plausible high-coupling files like `lib/utils.js`
  and `lib/core/AxiosError.js`). A repo in a third language (Go, Java, Rust,
  ...) shows an empty coupling table by design, not a broken one — extending
  further means implementing each additional language's own import/require
  syntax and resolution rules.
- **JS/TS import extraction is regex-based, not a real parser** (no
  lightweight JS AST parser in the Python ecosystem without adding a Node.js
  dependency). Covers the common `import`/`export ... from`, `require()`,
  and dynamic `import()` forms; can miss unusual formatting or false-positive
  on a look-alike string, the same class of tradeoff as the bug-fix keyword
  heuristic below.
- **Keyword-based bug labeling**, not a true SZZ implementation tracing
  bug-inducing commits via blame. This is the same simplification used in
  several cited papers' early baselines — call it out explicitly rather than
  overclaiming precision.
- **Single train/test split**, not the rolling-origin time-based evaluation
  used in more rigorous defect-prediction papers (e.g. Robredo et al., 2024).
  Reasonable extension if there's time.
- **Dependency graph resolves imports heuristically** (`_path_to_module` in
  `dependency_graph.py` strips a leading `src/`/`lib/` container dir, tries
  progressively shorter dotted-path prefixes). Works well for standard
  layouts; unconventional package structures may under- or over-resolve
  edges.
- `/recommend` caches only the *single most recent* `/analyze` result
  in-memory (by design — this is a one-demo-at-a-time tool, not a
  multi-tenant service). Analyzing a second repo evicts the first.
- LLM recommendations use plain JSON-in-the-prompt + manual Pydantic
  validation rather than the SDK's newer structured-output helpers
  (`messages.parse`), since those need a newer `anthropic` SDK version than
  what's pinned here. Functionally equivalent, just more portable.
