# EvoMind — Backend MVP

Predictive bug-proneness scoring from Git history and static code metrics,
plus LLM-generated refactoring recommendations for the riskiest files.
This is the first working slice of the full EvoMind proposal: it implements
the **Version Control Analysis Module**, **Source Code Analysis Module**, a
real **Predictive Analytics Module**, and a first cut of the **AI
Recommendation Module**, end to end, on real repositories.

## What it actually does

1. Clones/mines a repo's full commit history (`evomind/ingestion/git_miner.py`,
   via [PyDriller](https://pydriller.readthedocs.io/)).
2. Picks a **cutoff date** at `train_fraction` through the repo's history.
3. Computes, per file, using only commits at or before the cutoff:
   process metrics (churn, commit count, author count, prior bug-fix count,
   age, recency) and static metrics (LOC, cyclomatic complexity,
   maintainability index, Halstead volume/difficulty) on the file's content
   snapshot *as of the cutoff* (`evomind/metrics/code_metrics.py`, via
   [radon](https://radon.readthedocs.io/)).
4. Labels each file `is_bug_prone = 1` if a bug-fixing commit (keyword
   heuristic on commit messages — see `BUG_KEYWORDS` in `git_miner.py`)
   touches it strictly *after* the cutoff, within `horizon_days`.
5. Trains a Random Forest against a Logistic Regression baseline
   (`evomind/ml/train.py`), evaluated on a held-out split with precision,
   recall, F1, ROC-AUC, and average precision.
6. Re-scores the repo's *current* files (latest snapshot, full history) with
   the trained model to produce a live risk ranking.
7. On request (dashboard button, or `POST /recommend`), sends one risky
   file's metrics + source excerpt to Claude (`evomind/llm/recommend.py`)
   and returns a structured summary + prioritized refactoring suggestions.

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
evaluation, feature importances, live risk ranking, "AI recommendation"
button per file — light/dark). Or call `POST /analyze` directly with
`{"repo": "https://github.com/pallets/flask"}`, then `POST /recommend` with
`{"repo": "...", "file_path": "..."}` for one file's suggestions.
Interactive API docs at `http://127.0.0.1:8000/docs`.

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

- **Python-only.** `code_metrics.py` uses `radon`, which only parses Python.
  Multi-language support (the "graph-based software analysis" module in the
  proposal) is not yet built.
- **Keyword-based bug labeling**, not a true SZZ implementation tracing
  bug-inducing commits via blame. This is the same simplification used in
  several cited papers' early baselines — call it out explicitly rather than
  overclaiming precision.
- **Single train/test split**, not the rolling-origin time-based evaluation
  used in more rigorous defect-prediction papers (e.g. Robredo et al., 2024).
  Reasonable extension if there's time.
- No dependency-graph / architectural-coupling module yet — that's the next
  slice (the proposal's Software Architecture Analysis Module).
- `/recommend` caches only the *single most recent* `/analyze` result
  in-memory (by design — this is a one-demo-at-a-time tool, not a
  multi-tenant service). Analyzing a second repo evicts the first.
- LLM recommendations use plain JSON-in-the-prompt + manual Pydantic
  validation rather than the SDK's newer structured-output helpers
  (`messages.parse`), since those need a newer `anthropic` SDK version than
  what's pinned here. Functionally equivalent, just more portable.
