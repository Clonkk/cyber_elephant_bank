## README

Install uv: https://docs.astral.sh/uv/getting-started/installation/

Get deps : `uv sync`

Run server: `uv run app.py`  — then serve with gunicorn on the LAN:
`gunicorn app:server -b 0.0.0.0:5000` (single worker, see Procfile)

Generate pip compatible deps: `uv pip freeze > requirements.txt`

## Bank accounts

Each character has a fixed 5-character account ID (letters + digits):

| Account | ID | Initial balance |
|---|---|---|
| PNJs MDJ (bank) | 0PNJ0 | 1 000 000 |
| Silence | 32BGR | 2 400 |
| Zap | 40AZE | 2 000 |
| Sudo | 83XDF | 1 800 |
| Prof | 94POT | 1 600 |
| Apache | 74UYT | 1 200 |
| Vigie | 86LKD | 1 500 |
| Glock | 25KQN | 1 200 |
| Sabre | 39SPQ | 1 500 |
| Boston | 12NCZ | 800 |
| Diamond | 70AND | 1 600 |
| Yojimbo | 30MBO | 1 100 |
| Jab | 14EKG | 1 300 |
| Surin | 66SXF | 750 |
| Noise | 50MPT | 300 |
| Tank | 36ECV | 200 |
| Strat | 24FRD | 600 |
| Pixie Trust | 65OKN | 1 000 000 |
| Maverick | 15QZS | 1 000 000 |
| Wasp | 49YUP | 1 000 000 |

At init the bank seeds every account (its own doc starts at 4 019 850 =
1 000 000 + all player balances), so the treasury ends exactly at the
1 000 000 shown above.

- Players make transfers by typing the recipient's 5-character ID (full
  keyboard since IDs mix letters and digits; typing is case-insensitive, e.g.
  `32bgr` works). The bank's own account (0PNJ0) **is** a valid destination:
  anyone can send credits to the treasury.
- Invalid or unknown IDs and non-integer amounts produce explicit error
  messages — amounts are never silently rounded.
- The history shows account IDs instead of names (e.g. `32BGR → 94POT`),
  except the bank, which keeps its name (`PNJs MDJ`). The **admin ledger**
  instead shows `Name (ID) → Name (ID)`, e.g.
  `Silence (32BGR) → Prof (94POT)`.
- The header shows the logged-in user as `Name (account ID)`, e.g.
  `PNJs MDJ (0PNJ0)`.

## Admin panel

The admin panel (users in the `admin` group: **Maverick, Pixie Trust, Wasp,
Bank**) uses one dropdown for the target account and a **signed amount**:

- `+` (positive) → the bank **sends** credits to that account;
- `-` (negative) → credits are **taken from** that account (e.g. `-100`).

An account can never go below 0, and the bank cannot send more than it holds.
Admins don't see the standard player transfer form (the panel replaces it).
The panel comes with a **🛠 Administration** toggle (visible to admins only) to
collapse/expand it, and a live "Solde actuel" balance line for the selected
target. Every admin send/take appears **once** in the admin's own history
(tagged `Admin`) and in the target account's history, like any other
transaction; the view refreshes automatically after the operation.

## Admin ledger & public balances

Admins have a full ledger built from the global history doc (`__history__`),
i.e. **every** transaction, with three row styles:

- party rows (account ↔ bank, or the account's own rows), with balance chips;
- **purple** `Joueurs` rows for transfers between two players;
- neutral `Banque` rows for every bank-related event (init deposits, other
  admins' operations), shown with the sign of the money flow.

A "Afficher les transferts entre joueurs" switch (admins only) hides/shows the
purple rows.

Public balances live in the **Comptes** section — **admins only**: one chip
per account (players **and** the bank), showing `Name (ID)` and the current
balance. Regular players never see other characters' total credits.

## Hosting (Render/Railway/…)

- **Build command**: `pip install -r requirements.txt` (committed, pinned).
- **Start command** (the WSGI object is `server`, not `app`):

  ```
  gunicorn app:server -b 0.0.0.0:$PORT --workers 1 --threads 8
  ```

  `--workers 1` is mandatory (TinyDB is guarded by an in-process lock only).
- The database seeds itself on first boot (module import runs `db_init()`
  when `db.json` is missing), so a fresh deploy works without extra steps.
- Free tiers have an **ephemeral filesystem**: `db.json` resets on every
  deploy/restart/spin-down. Mount a persistent disk to keep balances, or
  accept that each deploy starts a fresh bank.
- Hosting publicly exposes the app (and the hardcoded BasicAuth passwords in
  the source): keep the repo private or change the passwords first.

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
