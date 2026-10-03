# Contributing

Thanks for helping. Bug reports, new scene types, provider fixes and docs are all welcome.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests     # ffmpeg must be on PATH for the upscale test
reelsmith render examples/carousel-crafter.json --draft    # renders without any model or network
```

## Reporting a problem

Please include the job log (open the job in the web app, then **Details**), how you run Reelsmith (Docker or not),
the provider and model you use, and `/api/status` output. Remove API keys before pasting anything.

## Pull requests

- Keep changes focused, and add or update a test in `tests/` when you fix a bug.
- New scene types go in `reelsmith/engine/scenes.py`: implement `budget()`, register sounds in `sounds()` using the same
  time constants the drawing uses, and add the type to `REGISTRY` and to the catalogue and schema in `storyboard.py`.
- New templates go in `reelsmith/engine/templates.py`: copy an entry, change its palette, fonts, shape, background
  style, transition, music and tone. A new background style is a `_bg_<name>` method in `engine/timeline.py`. Run the
  tests: they render every scene type in every template.
- A template's story structure lives in `reelsmith/blueprints.py`: which scene types it uses (`ALLOWED`), its
  opening scene (`OPENING`), how many repeated scenes fit a length (`counts`), what the model is told
  (`blueprint_text`), how other scene types are converted (`_convert`) and how the built-in planner fills it
  (`assemble`). `tests/` checks that every template's plan opens correctly and that all six differ.
- Content comes from language models, so never assume a string length: use `fit_size`, `fit_block` or `headline`.
- The web app is a single file with no build step (`reelsmith/web/index.html`); please keep it that way.
