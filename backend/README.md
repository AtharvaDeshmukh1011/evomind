# EvoMind backend (MVP)

Predictive bug-proneness scoring from Git history and static code metrics (with SZZ-refined labels), architectural coupling/cycle analysis, rolling- origin evaluation, and LLM-generated refactoring recommendations for the riskiest files. This is the first working slice of the full EvoMind proposal: it implements the **Version Control Analysis Module**, **Source Code Analysis Module**, **Software Architecture Analysis Module**, a real **Predictive Analytics Module**, and a first cut of the **AI Recommendation Module**, end to end, on real repositories.

## What it actually does

1. Clones a repo once locally (`evomind/ingestion/repo_source.py`) and mines its full commit history for process metrics (`evomind/ingestion/git_miner.py`, via [PyDriller](https://pydriller.readthedocs.io/)).
2. Picks a **cutoff date** at `train_fraction` through the repo's history, and resolves the exact commit at or before it (`evomind/ingestion/tree_snapshot.py`, via `git rev-list`).
3. Reads the *exact* file tree at that commit (and separately at `HEAD`) via `git archive`, not by replaying commit diffs chronologically (see "Why tree reads, not diff replay" below).
4. Computes, per file, using only commits at or before the cutoff: process metrics (churn, commit count, author count, prior bug-fix count, age, recency) and static metrics (LOC, cyclomatic complexity, function count) on the file's content snapshot *as of the cutoff* (`evomind/metrics/code_metrics.py`). Python files get the fuller [radon](https://radon.readthedocs.io/)-based analysis (adds maintainability index and Halstead metrics, since it parses a real AST); every other language [lizard](https://github.com/terryyin/lizard) supports (JS/TS, Java, Go, Ruby, C/C++, C#, PHP, Rust, Kotlin, Swift, and more) gets complexity/LOC via its tokenizer, with maintainability index and Halstead metrics explicitly defaulted to 0.0 rather than guessed.
5. Labels each file `is_bug_prone = 1` if a bug-fixing commit (keyword heuristic on commit messages; see `BUG_KEYWORDS` in `git_miner.py`) touches it strictly *after* the cutoff, within `horizon_days`, **then SZZ-refines that label** (`evomind/labeling/szz.py`): each candidate fix is traced back via `git blame` on its parent revision to find which commit last touched the lines it corrects, and the file only keeps the positive label if that inducing commit is at or before the cutoff. This catches a subtle leakage-adjacent flaw in the naive heuristic: without it, a defect introduced *after* the cutoff but fixed within the horizon would count as "predictable," even though no cutoff-time model could ever have seen evidence of it. See "Why SZZ instead of keyword matching" below. Optionally (`use_llm_szz=True`), each blame-identified candidate is additionally assessed by an LLM before being accepted (`evomind/labeling/llm_szz.py`), filtering out false positives blame alone can't distinguish from a real inducing change (a formatting pass, a rename, an unrelated refactor). See "LLM-assisted SZZ" below.
6. Trains a Random Forest against a Logistic Regression baseline (`evomind/ml/train.py`), evaluated on a held-out split with precision, recall, F1, ROC-AUC, and average precision, then **selects between them on measured ROC-AUC**: the selected model is the one that scores files in step 7. See "How the model is selected" below. A separate, opt-in **rolling-origin evaluation** (`evomind/ml/rolling_origin.py`, `scripts/rolling_origin_eval.py`) trains and tests across multiple chronologically-increasing cutoffs instead of one random split: see below.
7. Re-scores the repo's *current* files (latest snapshot) with the trained model to produce a live risk ranking.
8. Parses every current **Python, JS/TS, and Java** file's imports and builds an intra-repo dependency graph (`evomind/architecture/dependency_graph.py`), computing afferent/efferent coupling, instability, and circular-dependency groups (via Tarjan's SCC algorithm). Python imports are parsed with the stdlib `ast` module and resolved to dotted module names; JS/TS imports (`import`/`export ... from`, `require()`, dynamic `import()`) are extracted with a regex and resolved as relative file paths, the way Node/bundler resolution actually works; Java imports are resolved as fully-qualified class names built from each file's own `package` declaration (self-describing, unlike Python's directory-only convention: no source-root guessing needed). All three drop external/stdlib imports rather than producing external nodes. Other languages are skipped entirely for this step (see limitations); such a repo shows an empty coupling panel rather than an error.
9. On request (dashboard button, or `POST /recommend`), sends one risky file's metrics + source excerpt to an LLM via Groq (`evomind/llm/recommend.py`) and returns a structured summary + prioritized refactoring suggestions.

### Why tree reads, not diff replay

An earlier version reconstructed "current file content" by replaying every commit's add/modify/delete/rename chronologically and mutating a shared dict. This is unsound under non-linear history: a long-lived branch created *before* a rename, merged *after* it, gets visited by PyDriller in commit-date order: so a file already renamed away on the mainline gets resurrected by that branch's later-dated (but logically earlier) commits. This happened for real on Flask's history (`flask/app.py` → `src/flask/app.py` in 2019, then reappearing because a pre-rename branch merged weeks later). `git rev-list` + `git archive` sidestep it entirely by resolving one exact commit and reading its tree directly: no diff replay, no ambiguity. `tests/test_tree_snapshot.py` covers this.

### How the model is selected

Nothing about the choice is hardcoded or assumed: both models are fitted on the same 70% training split, both are scored on the same held-out 30%, and `_build_report` in `evomind/ml/train.py` picks the winner with a single `max(report.results, key=_selection_key)`. That name is what the dashboard shows as "Best model", and (this is the part that matters) the same object is what `pipeline.py` then calls `predict_proba` on to produce every risk score in the ranking. So "best model" is never a label with a different model behind it.

`_selection_key` ranks on **ROC-AUC, with F1 only as a tiebreak**. The reason is that the product output is a *ranking* of files by risk score, not a binary accept/reject at the 0.5 probability threshold that precision/recall/F1 are computed at. ROC-AUC measures exactly the property the ranking depends on (is a genuinely bug-prone file scored above a clean one) whereas F1 measures quality at one arbitrary cut point. The rolling-origin runs make this concrete rather than theoretical: on Click, ROC-AUC held steady across folds (0.795-0.882) while F1 swung far wider (0.417-0.690), so F1 is measurably the noisier quantity to select on.

Two consequences worth stating plainly:

- **The winner varies by repository, and that's the point.** A run reporting the logistic baseline isn't a failure: it says that repo's signal is close to linearly separable in these 16 features. Reporting a strong model with no baseline to compare against would be the weaker result.
- **Feature importances follow the selected model**, because the two expose different quantities: mean decrease in impurity for the forest, absolute standardized coefficients for the logistic pipeline (comparable across features only because it standardizes them first). Both are normalized to sum to 1, and the dashboard panel is labeled with which one it is rather than always claiming "Random Forest importances".

`tests/test_train.py` pins all of this, including the regression case that motivated it: an earlier version always assigned the forest as the scorer while still reporting a winner by metric, so the dashboard could announce one model over a ranking the other had produced.

### Why the cutoff/horizon split matters

Features only ever see commits at or before the cutoff; the label only ever looks strictly after it. This is what keeps the evaluation honest: without it, "predicting" bugs is trivial because the model can see the bug-fix commit itself. `tests/test_feature_builder.py` has an explicit regression test for this (`test_pre_cutoff_bug_fix_does_not_leak_into_label`).

### Why SZZ instead of keyword matching

"A bug-fixing commit touched this file within the horizon" sounds like a clean label, but it conflates two different things: *when the fix happened* and *when the defect was actually introduced*. A fix landing at day 40 of a 365-day horizon might be repairing a defect introduced at day 35 (genuinely predictable from cutoff-time information) or one introduced at day 38: after the cutoff a model trained "as of cutoff" could ever have existed for. The naive heuristic labels both cases identically as `is_bug_prone = 1`. SZZ (Śliwerski, Zimmermann, Zeller, 2005) resolves this by tracing each fix's diff back to whichever earlier commit last touched the corrected lines (the actual bug-inducing commit) via `git blame` on the fix's parent revision, and the label survives only if that commit is at or before the cutoff. Scope, deliberately: this refines *when* the label fires, not *which file* it fires on: in the large majority of real fixes the inducing change lives in the same file the fix touches anyway, so this doesn't relabel to a different file; it filters out temporally-invalid positives. See `evomind/labeling/szz.py`'s module docstring for the full reasoning and known SZZ limitations (merge/root commits are skipped; cosmetic "fixes" that happen to match the bug-fix keyword regex aren't special-cased). `tests/test_szz.py` covers the tracing logic against a real git repo (not mocked), including the leakage regression case directly.

### LLM-assisted SZZ (opt-in)

Plain SZZ has its own known weakness: `git blame` is a purely line-level heuristic, so "the commit that last touched these lines" is often *not* the commit that actually introduced the defect: it can be a formatting pass, a rename, or an unrelated refactor that happened to touch the same line. `evomind/labeling/llm_szz.py` addresses this by giving an LLM both the fix's diff and each blame-identified candidate's own diff, and asking it to assess whether the candidate is a plausible genuine cause or a false positive. It follows **LLM4SZZ** (Zhou et al., 2025, [arXiv:2504.01404](https://arxiv.org/abs/2504.01404), ACM Proceedings on Software Engineering), which reports this approach beating heuristic-only SZZ baselines by 6.9–16% F1. Related work exploring similar LLM-assisted SZZ variants: AgenticSZZ, AgentSZZ, MAS-SZZ. **This is an applied technique following a published approach, not a novel contribution of this project**: worth being explicit about in a report or defense rather than overclaiming it.

Design notes:
- **Only filters, never adds.** A candidate the LLM confirms is exactly what plain SZZ would have accepted anyway; a candidate it rejects is removed. It can never surface a bug-inducing commit blame-based tracing didn't already find.
- **Bounded cost, same scope as plain SZZ.** Only positively-labeled files are considered, and a candidate is only sent to the LLM if it already passes the cutoff-date check: no LLM call is spent on a candidate the date alone already disqualifies.
- **Opt-in, not automatic** (`use_llm_szz=True` on `run_pipeline`, or the checkbox in the dashboard). Runs against **Groq** (free API tier, no paid key needed): same provider as the `/recommend` endpoint. Needs `GROQ_API_KEY`; without one, every candidate falls back to plain-SZZ behavior (accepted, since it already passed the date check) rather than crashing or silently dropping a label plain SZZ would have kept. `AssessmentStats` (`assessed` vs. `fallback` counts) makes this visible rather than silent: the dashboard shows a warning if every candidate fell back, so "I turned this on and it didn't error" is never confused with "it actually ran."

### Rolling-origin evaluation

The main pipeline's `train_and_evaluate` does a single random (stratified) train/test split within one snapshot: fast, but the split has nothing to do with time, so it can't show whether a model trained on older data still holds up on genuinely newer data. `evomind/ml/rolling_origin.py` does that properly: it builds a feature table at each of several chronologically- increasing cutoffs (each independently SZZ-refined), then evaluates every adjacent pair as a fold: train on fold *i*, test purely on fold *i+1*, a later period the model never saw. This is the walk-forward protocol closer to what the more rigorous cited papers use (e.g. Robredo et al., 2024's time-dependent methods), and it directly answers what a single split can't: is performance stable across time, or did evaluation get lucky (or unlucky) with one arbitrary split?

This is deliberately **not** part of the interactive `/analyze` path: it repeats the expensive per-cutoff work (tree read + code metrics for every file, SZZ tracing) once per fold, so it multiplies analysis time by roughly the fold count. Run it separately for a report-quality evaluation:

```bash
.venv/Scripts/python.exe scripts/rolling_origin_eval.py --repo https://github.com/pallets/click
```

On real data (Click, 3 cutoffs → 2 folds), this actually surfaces a genuine finding worth reporting: ROC-AUC stayed stable across folds (0.795–0.882) while F1 swung more (0.417–0.690): evidence the model's probability *ranking* generalizes across time better than its default classification threshold does. That's exactly the kind of insight a single train/test split can't show you.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Two features are LLM-backed and optional: the ML pipeline, dashboard, and `/analyze` all work fine with no key set. Both run on **Groq** (free tier: sign up at [console.groq.com](https://console.groq.com), no card required):

- The "AI recommendation" button / `/recommend` endpoint.
- The opt-in "Use LLM-assisted SZZ" checkbox.

Easiest way to set it: create `backend/.env` (already gitignored: never commit it) with:

```bash
GROQ_API_KEY=your_groq_api_key_here
```

`evomind/api/main.py` loads it automatically on startup via `python-dotenv`. Equivalent without a `.env` file:

```bash
export GROQ_API_KEY=your_groq_api_key_here   # PowerShell: $env:GROQ_API_KEY = "your_groq_api_key_here"
```

Without a key, `/recommend` fails with a clear 502 error message rather than crashing; LLM-assisted SZZ falls back to plain SZZ (with a visible warning in the dashboard) rather than failing at all: both safe to leave unset while demoing the rest of the system.

By default, only Git URLs can be analyzed: passing a local filesystem path is rejected. To opt into analyzing local repos, set `EVOMIND_ALLOWED_LOCAL_REPO_ROOT` to a folder; only paths inside it are then allowed:

```bash
export EVOMIND_ALLOWED_LOCAL_REPO_ROOT=/path/to/repos   # PowerShell: $env:EVOMIND_ALLOWED_LOCAL_REPO_ROOT = "C:\path\to\repos"
```

See "Security considerations" below for why this exists.

## Run the pipeline from the CLI

```bash
.venv/Scripts/python.exe scripts/run_pipeline.py --repo https://github.com/pallets/flask
```

Prints held-out evaluation metrics, top feature importances, and the current top-risk files, and saves `data/<name>_features.csv` and `data/<name>_risk_scores.csv`.

Useful flags: `--horizon-days`, `--train-fraction`, `--out-name`, `--top-n`. Works on any local path or public Git URL: swap `--repo` for whatever you're demoing (a known repo is more convincing to an examiner than a toy one).

## Run the API + dashboard

```bash
.venv/Scripts/python.exe -m uvicorn evomind.api.main:app --reload
```

Open `http://127.0.0.1:8000/` for the dashboard (repo input, **live progress during analysis**, an opt-in "Use LLM-assisted SZZ" checkbox, model evaluation, feature importances, sortable/filterable risk ranking, architectural coupling + circular dependencies (also sortable/filterable), "AI recommendation" button per file, light and dark themes). The dashboard drives `GET /analyze/stream` (Server-Sent Events) so the ~1–3 minute wait shows real per-stage progress: "Mining commit history…", "Tracing bug-inducing commits (SZZ)…" and so on, instead of a static message; `POST /analyze` (used by `scripts/run_pipeline.py` and tests) returns the same result as one JSON blob, no streaming, for programmatic use. Both accept `use_llm_szz`. Then `POST /recommend` with `{"repo": "...", "file_path": "..."}` for one file's suggestions. Interactive API docs at `http://127.0.0.1:8000/docs`.

**Expect roughly 1–3 minutes per analysis**: it walks the repo's full commit history once (cloning it locally first so nothing is fetched twice). Flask (~2000 commits, 94 files) takes about 90–150s; Java's Gson (207 files) took 65s in testing; smaller repos are faster. SZZ tracing adds some of that time, but it's bounded: it only traces files currently labeled positive, not every fix commit in the repo's history. Don't run concurrent `/analyze` requests against the same server: the underlying clone/mining is CPU- and I/O-heavy and multiple runs at once will make all of them slower rather than share the wait.

## Explanations, risk trends and pull-request checks

**Why is this file risky?** Every scored file carries up to three reasons, computed by ablation (`evomind/ml/explain.py`): each feature is reset to the repository's median value and the drop in predicted risk is measured. A reason such as `churn 6,405 · top 2% · +0.14` means "this file's churn is in the top 2% of the repository, and if it were typical, its risk would fall by 0.14". It works for both models, needs no extra dependency, and the stated impact is exactly what the model does (`tests/test_explain.py` checks this directly).

**Risk trend.** The repository is re-scored at six points in its history, from 30% of the way through to today (`evomind/ml/trend.py`), using the same trained model. The dashboard shows a sparkline per file, and the Trend column sorts by how much a file's risk has changed. Points before the training cutoff are partly in-sample for the model, so read the trend as direction, not as a forecast.

**Pull-request check** (`evomind/pr_risk.py`, `evomind/integrations/github.py`). Scores the files a PR changes against an analysis of the repository, and renders a report showing risk, trend and reasons. It can run in two ways:

- **From the dashboard:** after an analysis, enter a PR number in the "Pull request risk check" panel. Posting the result as a PR comment is opt-in.
- **Automatically, through a GitHub webhook:** point a repository webhook at `POST /webhook/github` (content type `application/json`, events: *Pull requests*). GitHub expects a reply within 10 seconds and an analysis takes minutes, so the endpoint replies `202` immediately and does the work in the background. Analyses are cached per repository for 6 hours. Each PR gets **one** comment, which later pushes update in place. `GET /webhook/github/recent` lists the last 20 webhook outcomes.

Settings (put them in `backend/.env`):

```bash
GITHUB_TOKEN=your_github_token_here            # needed to post comments; also raises GitHub's API rate limit
GITHUB_WEBHOOK_SECRET=your_webhook_secret_here   # needed for /webhook/github; the same value goes in GitHub's webhook form
```

Use a fine-grained token restricted to your own repository, with *Pull requests: Read and write*. Every webhook request is verified with HMAC-SHA256 against the secret, and unsigned or forged requests are rejected with `401`. Without a secret, the webhook endpoint is disabled (`503`). GitHub cannot reach `localhost`, so to try webhooks locally, expose the server with a tunnel such as `ngrok http 8000` and use the public URL it prints.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests/ -v
```

## Known limitations

- **Long histories are capped at the most recent 20,000 commits** (`MAX_COMMITS` in `evomind/ingestion/tree_snapshot.py`), so very large repositories finish in minutes. Older history is ignored, which can lower accuracy on long-lived projects.
- **Source files over 500 KB are skipped** (`MAX_SOURCE_BYTES`) as generated data, such as embedded probability tables, which would otherwise make code metrics take many minutes.
- **Dependency graph / coupling analysis covers Python, JS/TS, and Java only.** Bug-proneness prediction (the core pipeline) works on any language lizard supports: validated end-to-end on real JS/TS repos (e.g. axios) with zero Python files, and the coupling panel covers three languages now too (validated for real: axios → 305 JS/TS edges with plausible high-coupling files like `lib/utils.js`; Gson → 986 Java edges, `Gson.java` correctly identified as the single most depended-on class). A repo in a fourth language (Go, Rust, ...) shows an empty coupling table by design, not a broken one: extending further means implementing that language's own import/require syntax and resolution rules.
- **JS/TS and Java import extraction are regex-based, not real parsers** (no lightweight JS/Java AST parser in the Python ecosystem without adding a JVM/Node.js dependency). Covers the common import forms for each (`import`/`export ... from`, `require()`, dynamic `import()` for JS/TS; `import a.b.C;` and wildcard `import a.b.*;` for Java, resolved via each file's own `package` declaration); can miss unusual formatting or false-positive on a look-alike string inside a comment/string literal: the same class of tradeoff as the SZZ bug-fix keyword heuristic.
- **SZZ has known, literature-documented limitations**, shared by this implementation: merge and root commits are skipped (diffing against which parent, or nothing to blame, respectively); no special-casing for cosmetic/whitespace-only "fixes" or refactors that happen to match the bug-fix keyword regex; single blame pass, not the refinements later SZZ variants add (e.g. filtering out formatting-only inducing changes).
- **Dependency graph resolves Python imports heuristically** (`_path_to_module` in `dependency_graph.py` strips a leading `src/`/`lib/` container dir, tries progressively shorter dotted-path prefixes). Works well for standard layouts; unconventional package structures may under- or over-resolve edges. (Java's resolution is exact, not heuristic: package declarations are self-describing.)
- **Rolling-origin evaluation is opt-in, not automatic.** It's available both as a CLI script (`scripts/rolling_origin_eval.py`) and as a separate "Run rolling-origin evaluation" button in the dashboard (its own `GET /rolling-origin/stream` endpoint): but never runs as part of the main `/analyze` flow, since it repeats the expensive per-cutoff work once per fold. See the "Rolling-origin evaluation" section above for why.
- `/recommend` caches only the *single most recent* `/analyze` result in-memory (by design: this is a one-demo-at-a-time tool, not a multi-tenant service). Analyzing a second repo evicts the first.
- LLM recommendations use plain JSON-in-the-prompt + manual Pydantic validation rather than any SDK-specific structured-output helper, so the same pattern works unchanged if the backing model/provider ever changes.

## Security considerations

EvoMind is built for local, single-operator use (a laptop demo, a personal dev tool): not as a shared service handling proprietary codebases. Worth being explicit about what that does and doesn't cover, rather than silently assuming it's fine.

**What's actually safe today:**
- The core pipeline (mining commits, computing code metrics, building the dependency graph, training/scoring the model) runs **entirely locally**: no network calls at all beyond the initial `git clone` of the repo itself.
- Git subprocess calls use argument lists (`subprocess.run(["git", "clone", ...])`), never a shell string, so a malicious repo URL can't inject shell commands.
- Only two features send anything off the machine: the "AI recommendation" button and the "LLM-assisted SZZ" checkbox, both opt-in per click/toggle, both now explicitly labeled in the UI with exactly what gets sent and where (a file's source/metrics, or a commit's diff, to Groq's API).

**Hardening already in place, closing gaps a real deployment would hit:**
- `CORSMiddleware` is scoped to `localhost`/`127.0.0.1`, not `allow_origins=["*"]`: a wildcard would let any website's JavaScript call this API from a visitor's browser if it were ever network-reachable.
- Local repo paths are rejected unless `EVOMIND_ALLOWED_LOCAL_REPO_ROOT` is explicitly set, and then only paths inside that root are allowed (`_validate_repo_arg` in `evomind/api/main.py`). Without this, the API would let any caller point the server at *any* folder on its filesystem: there's otherwise no concept of "should this caller be allowed to read this path."
- Cloning a private repo without credentials fails in about a second with a clear message, instead of hanging indefinitely waiting for a username/password prompt (or a GUI credential-manager popup on Windows) that can never be answered (`GIT_TERMINAL_PROMPT=0` / `GCM_INTERACTIVE=never` in `evomind/ingestion/repo_source.py`, plus a timeout as a backstop).

**Deliberately out of scope, and why:**
- **No authentication.** Anyone who can reach the server can call any endpoint. Fine for a single operator on localhost; not fine the moment this is reachable by anyone else.
- **No per-user repo permissions.** EvoMind has no concept of "is this caller allowed to see this repo" beyond the path/CORS restrictions above: doing that properly means OAuth-integrating with the actual repo host (GitHub/GitLab) so *their* access control is what's enforced, using the requesting user's own token to clone rather than a server-wide credential. That's a real, separate project (a different kind of engineering effort than the ML/analysis work this capstone is actually about) not a same-afternoon addition.
- **If ever deployed with its own stored Git credentials** (an SSH key or token kept on the server for convenience), it becomes a confused-deputy risk: anyone who can call the API could use *that* access, regardless of whether they personally have permission to see the repo in question. This is the exact shape of problem a company handling genuinely confidential code has to solve properly: EvoMind doesn't attempt to here, and shouldn't be deployed that way without adding the OAuth-based access control above first.
