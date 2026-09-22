## README

Install uv: https://docs.astral.sh/uv/getting-started/installation/

Get deps : `uv sync`

Run server: `uv run app.py`

Generate pip compatible deps: `uv pip freeze > requirements.txt`

## Notes

- `app.py` is the current mobile-first (dark theme) version. The previous
  version is kept as `app_legacy.py`.
- Bootstrap 5.3 / Bootswatch "Cyborg" CSS is vendored in `assets/` (with
  gruvbox-inspired high-contrast palette overrides in `assets/custom.css`) so
  the app works fully offline on the LAN (no CDN dependency).
- gunicorn must run with a single worker (`Procfile` sets `--workers 1`):
  TinyDB is guarded by an in-process lock only.
