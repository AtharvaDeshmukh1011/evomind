# EvoMind

EvoMind reads a Git repository's commit history, learns which files went on to need bug fixes, and ranks today's files by the chance that they will need one next.

**Live demo:** [evomindai.vercel.app](https://evomindai.vercel.app) (also on [Hugging Face](https://huggingface.co/spaces/Deshmukh09/evomind))

The online demo replays saved analyses of pallets/click, pallets/flask, psf/requests and django/django. To scan any repository, run EvoMind locally.

Setup, architecture, and the full method are in [backend/README.md](backend/README.md).
