# EvoMind — Backend MVP

Predictive bug-proneness scoring from Git history and static code metrics
(with SZZ-refined labels), architectural coupling/cycle analysis, rolling-
origin evaluation, and LLM-generated refactoring recommendations for the
riskiest files. This is the first working slice of the full EvoMind
proposal: it implements the **Version Control Analysis Module**, **Source
Code Analysis Module**, **Software Architecture Analysis Module**, a real
**Predictive Analytics Module**, and a first cut of the **AI Recommendation
Module**, end to end, on real repositories.

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
   touches it strictly *after* the cutoff, within `horizon_days` — **then
   SZZ-refines that label** (`evomind/labeling/szz.py`): each candidate fix
   is traced back via `git blame` on its parent revision to find which
   commit last touched the lines it corrects, and the file only keeps the
   positive label if that inducing commit is at or before the cutoff. This
   catches a subtle leakage-adjacent flaw in the naive heuristic — without
   it, a defect introduced *after* the cutoff but fixed within the horizon
   would count as "predictable," even though no cutoff-time model could ever
   have seen evidence of it. See "Why SZZ, not just keyword-matching" below.
6. Trains a Random Forest against a Logistic Regression baseline
   (`evomind/ml/train.py`), evaluated on a held-out split with precision,
   recall, F1, ROC-AUC, and average precision. A separate, opt-in
   **rolling-origin evaluation** (`evomind/ml/rolling_origin.py`,
   `scripts/rolling_origin_eval.py`) trains and tests across multiple
   chronologically-increasing cutoffs instead of one random split — see
   below.
7. Re-scores the repo's *current* files (latest snapshot) with the trained
   model to produce a live risk ranking.
8. Parses every current **Python, JS/TS, and Java** file's imports and
   builds an intra-repo dependency graph
   (`evomind/architecture/dependency_graph.py`), computing afferent/efferent
   coupling, instability, and circular-dependency groups (via Tarjan's SCC
   algorithm). Python imports are parsed with the stdlib `ast` module and
   resolved to dotted module names; JS/TS imports (`import`/`export ... from`,
   `require()`, dynamic `import()`) are extracted with a regex and resolved
   as relative file paths, the way Node/bundler resolution actually works;
   Java imports are resolved as fully-qualified class names built from each
   file's own `package` declaration (self-describing, unlike Python's
   directory-only convention — no source-root guessing needed). All three
   drop external/stdlib imports rather than producing external nodes. Other
   languages are skipped entirely for this step (see limitations); such a
   repo shows an empty coupling panel rather than an error.
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

### Why SZZ, not just keyword-matching

"A bug-fixing commit touched this file within the horizon" sounds like a
clean label, but it conflates two different things: *when the fix
happened* and *when the defect was actually introduced*. A fix landing at
day 40 of a 365-day horizon might be repairing a defect introduced at day
35 (genuinely predictable from cutoff-time information) or one introduced
at day 38 — after the cutoff a model trained "as of cutoff" could ever have
existed for. The naive heuristic labels both cases identically as
`is_bug_prone = 1`. SZZ (Śliwerski, Zimmermann, Zeller, 2005) resolves this
by tracing each fix's diff back to whichever earlier commit last touched
the corrected lines — the actual bug-inducing commit — via `git blame` on
the fix's parent revision, and the label survives only if that commit is at
or before the cutoff. Scope, deliberately: this refines *when* the label
fires, not *which file* it fires on — in the large majority of real fixes
the inducing change lives in the same file the fix touches anyway, so this
doesn't relabel to a different file, just filters out temporally-invalid
positives. See `evomind/labeling/szz.py`'s module docstring for the full
reasoning and known SZZ limitations (merge/root commits are skipped;
cosmetic "fixes" that happen to match the bug-fix keyword regex aren't
special-cased). `tests/test_szz.py` covers the tracing logic against a real
git repo (not mocked), including the leakage regression case directly.

### Rolling-origin evaluation

The main pipeline's `train_and_evaluate` does a single random (stratified)
train/test split within one snapshot — fast, but the split has nothing to
do with time, so it can't show whether a model trained on older data still
holds up on genuinely newer data. `evomind/ml/rolling_origin.py` does that
properly: it builds a feature table at each of several chronologically-
increasing cutoffs (each independently SZZ-refined), then evaluates every
adjacent pair as a fold — train on fold *i*, test purely on fold *i+1*, a
later period the model never saw. This is the walk-forward protocol closer
to what the more rigorous cited papers use (e.g. Robredo et al., 2024's
time-dependent methods), and it directly answers what a single split can't:
is performance stable across time, or did evaluation just get lucky (or
unlucky) with one arbitrary split?

This is deliberately **not** part of the interactive `/analyze` path — it
repeats the expensive per-cutoff work (tree read + code metrics for every
file, SZZ tracing) once per fold, so it multiplies analysis time by roughly
the fold count. Run it separately for a report-quality evaluation:

```bash
.venv/Scripts/python.exe scripts/rolling_origin_eval.py --repo https://github.com/pallets/click
```

On real data (Click, 3 cutoffs → 2 folds), this actually surfaces a genuine
finding worth reporting: ROC-AUC stayed stable across folds (0.795–0.882)
while F1 swung more (0.417–0.690) — evidence the model's probability
*ranking* generalizes across time better than its default classification
threshold does. That's exactly the kind of insight a single train/test
split can't show you.

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

Open `http://127.0.0.1:8000/` for the dashboard (repo input, **live progress
during analysis**, model evaluation, feature importances, sortable/
filterable risk ranking, architectural coupling + circular dependencies
(also sortable/filterable), "AI recommendation" button per file — light/
dark). The dashboard drives `GET /analyze/stream` (Server-Sent Events) so
the ~1–3 minute wait shows real per-stage progress — "Mining commit
history…", "Tracing bug-inducing commits (SZZ)…", etc. — instead of a
static message; `POST /analyze` (used by `scripts/run_pipeline.py` and
tests) returns the same result as one JSON blob, no streaming, for
programmatic use. Then `POST /recommend` with `{"repo": "...", "file_path": "..."}`
for one file's suggestions. Interactive API docs at `http://127.0.0.1:8000/docs`.

**Expect roughly 1–3 minutes per analysis** — it walks the repo's full
commit history once (cloning it locally first so nothing is fetched twice).
Flask (~2000 commits, 94 files) takes about 90–150s; Java's Gson (207 files)
took 65s in testing; smaller repos are faster. SZZ tracing adds some of
that time, but it's bounded — it only traces files currently labeled
positive, not every fix commit in the repo's history. Don't run concurrent
`/analyze` requests against the same server — the underlying clone/mining
is CPU- and I/O-heavy and multiple runs at once will make all of them
slower, not just share the wait.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests/ -v
```

## Known limitations (be upfront about these in the defense — it reads as rigor, not weakness)

- **Dependency graph / coupling analysis covers Python, JS/TS, and Java
  only.** Bug-proneness prediction (the core pipeline) works on any language
  lizard supports — validated end-to-end on real JS/TS repos (e.g. axios)
  with zero Python files, and the coupling panel covers three languages now
  too (validated for real: axios → 305 JS/TS edges with plausible
  high-coupling files like `lib/utils.js`; Gson → 986 Java edges, `Gson.java`
  correctly identified as the single most depended-on class). A repo in a
  fourth language (Go, Rust, ...) shows an empty coupling table by design,
  not a broken one — extending further means implementing that language's
  own import/require syntax and resolution rules.
- **JS/TS and Java import extraction are regex-based, not real parsers** (no
  lightweight JS/Java AST parser in the Python ecosystem without adding a
  JVM/Node.js dependency). Covers the common import forms for each
  (`import`/`export ... from`, `require()`, dynamic `import()` for JS/TS;
  `import a.b.C;` and wildcard `import a.b.*;` for Java, resolved via each
  file's own `package` declaration); can miss unusual formatting or
  false-positive on a look-alike string inside a comment/string literal —
  the same class of tradeoff as the SZZ bug-fix keyword heuristic.
- **SZZ has known, literature-documented limitations**, shared by this
  implementation: merge and root commits are skipped (diffing against which
  parent, or nothing to blame, respectively); no special-casing for
  cosmetic/whitespace-only "fixes" or refactors that happen to match the
  bug-fix keyword regex; single blame pass, not the refinements later SZZ
  variants add (e.g. filtering out formatting-only inducing changes).
- **Dependency graph resolves Python imports heuristically**
  (`_path_to_module` in `dependency_graph.py` strips a leading `src/`/`lib/`
  container dir, tries progressively shorter dotted-path prefixes). Works
  well for standard layouts; unconventional package structures may under- or
  over-resolve edges. (Java's resolution is exact, not heuristic — package
  declarations are self-describing.)
- **Rolling-origin evaluation is opt-in, not automatic.** It's a separate,
  slower script (`scripts/rolling_origin_eval.py`) rather than part of
  `/analyze`, since it repeats the expensive per-cutoff work once per fold —
  see the "Rolling-origin evaluation" section above for why.
- `/recommend` caches only the *single most recent* `/analyze` result
  in-memory (by design — this is a one-demo-at-a-time tool, not a
  multi-tenant service). Analyzing a second repo evicts the first.
- LLM recommendations use plain JSON-in-the-prompt + manual Pydantic
  validation rather than the SDK's newer structured-output helpers
  (`messages.parse`), since those need a newer `anthropic` SDK version than
  what's pinned here. Functionally equivalent, just more portable.
