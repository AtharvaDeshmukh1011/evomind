---
title: EvoMind
emoji: 🦎
colorFrom: indigo
colorTo: gray
sdk: static
pinned: false
short_description: Predicts which files will need a bug fix next
tags:
  - software-engineering
  - defect-prediction
  - code-quality
  - machine-learning
  - git
---

# EvoMind

**Know which files will break next, before they do.**

EvoMind reads a Git repository's commit history, learns which files went on to need bug fixes, and ranks today's files by the chance that they will need one next. Each score comes with the reasons behind it, a trend over time, and a map of the import loops that tie the codebase together.

![EvoMind](https://raw.githubusercontent.com/AtharvaDeshmukh1011/evomind/master/brag-output/brag.jpg)

## This Space

This is the online showcase. It replays saved analyses of **pallets/click**, **pallets/flask**, **psf/requests** and **django/django** in the full dashboard: pick one on the front page and explore the results. To scan any repository of your own, run EvoMind locally (see below).

## What you can explore

- **Risk ranking:** every file scored 0–1 by its chance of needing a bug fix within 365 days
- **Reasons:** up to three per file, e.g. `churn 6,405 · top 2% · +0.14`
- **Risk trend:** how each file's risk changed across six points in history
- **Architecture:** coupling and circular-import groups (Tarjan's algorithm)
- **Model evaluation:** Random Forest vs. Logistic Regression, selected by ROC-AUC on held-out files

## How it works

1. Mine the full commit history and pick a cutoff date partway through it.
2. Measure each file at the cutoff: churn, commits, authors, past fixes, age, size, complexity.
3. Label files that needed a bug fix after the cutoff, refined with **SZZ** so only defects introduced before the cutoff count.
4. Train both models on 70% of files, test on the other 30%, and keep the one with the higher ROC-AUC.
5. Score today's files and explain each score by resetting features to the repository median.

## Results

| Repository | Selected model | ROC-AUC | F1 |
|---|---|---:|---:|
| django/django | Random Forest | 0.911 | 0.588 |
| pallets/flask | Logistic Regression | 0.900 | 0.571 |
| psf/requests | Logistic Regression | 0.833 | 0.571 |
| pallets/click | Random Forest | 0.812 | 0.400 |

On a time-based (rolling-origin) evaluation, where the model is tested on a later period it never saw, ROC-AUC stays at 0.668 ± 0.006 on Flask and 0.795–0.882 on Click.

## Run it on any repository

```bash
git clone https://github.com/AtharvaDeshmukh1011/evomind.git
cd evomind/backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m uvicorn evomind.api.main:app
```

Then open http://127.0.0.1:8000 and paste a public repository URL.

## Links

- Source code and full documentation: [github.com/AtharvaDeshmukh1011/evomind](https://github.com/AtharvaDeshmukh1011/evomind)
- Main demo: [evomindai.vercel.app](https://evomindai.vercel.app)

Credits: the head on the opening page is from "Infinite, 3D Head Scan" by Lee Perry-Smith (Infinite Realities), CC BY 3.0, via the three.js examples. Sound effects are CC0 recordings from Freesound.
