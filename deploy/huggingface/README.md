---
title: EvoMind
emoji: 🦎
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Predicts which files in a Git repository will need a bug fix next
---

# EvoMind

EvoMind reads a repository's commit history, learns which files went on to need bug fixes, and ranks today's files by the chance that they will need one next.

This is the public demo. Paste a public GitHub URL and press Analyze. Live analyses run one at a time; repeat requests for the same repository within six hours return instantly. AI recommendations and posting PR comments are switched off here, and repositories over 400 MB are refused.

Source code and full documentation: https://github.com/AtharvaDeshmukh1011/evomind
