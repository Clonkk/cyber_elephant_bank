## README

Install uv: https://docs.astral.sh/uv/getting-started/installation/

Get deps : `uv sync`

Run server: `uv run app.py`  — then serve with gunicorn on the LAN:
`gunicorn app:server -b 0.0.0.0:5000` (single worker, see Procfile)

Generate pip compatible deps: `uv pip freeze > requirements.txt`

## Bank accounts

Each character has a fixed 5-digit account number:

| Account | ID | Initial balance |
|---|---|---|
| Naoned cyber bank | 00001 | 10 000 000 |
| Sinistre | 00002 | 1 500 |
| Prof | 00003 | 700 |
| Pixie | 00004 | 50 000 |
| Maverick | 00005 | 50 000 |

- Players make transfers by typing the recipient's 5-digit ID (numeric
  keyboard). The bank's own ID (00001) is not a valid destination.
- Invalid or unknown IDs and non-integer amounts produce explicit error
  messages — amounts are never silently rounded.
- The history shows account IDs instead of names (e.g. `00004 → 00003`),
  except the bank, which keeps its name (`Naoned cyber bank`).

## Admin panel

The admin panel (users in the `admin` group: Maverick, Pixie, Bank) uses one
dropdown for the target account and a **signed amount**:

- `+` (positive) → the bank **sends** credits to that account;
- `-` (negative) → credits are **taken from** that account (e.g. `-100`).

An account can never go below 0, and the bank cannot send more than it holds.
Every admin send/take also appears in the admin's own history (tagged
`Admin`) and in the target account's history, like any other transaction.

## Notes

- `app.py` is the current mobile-first (dark theme) version. The previous
  version is kept as `app_legacy.py`.
- Bootstrap 5.3 / Bootswatch "Cyborg" CSS is vendored in `assets/` (with
  gruvbox-inspired high-contrast palette overrides in `assets/custom.css`) so
  the app works fully offline on the LAN (no CDN dependency).
- gunicorn must run with a single worker (`Procfile` sets `--workers 1`):
  TinyDB is guarded by an in-process lock only.
- `db.json` (created on first run) is gitignored; delete it or use the admin
  reset to start over.
