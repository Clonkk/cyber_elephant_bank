import os
from threading import RLock
from time import localtime, strftime, time

import dash_bootstrap_components as dbc
from dash import (
    callback,
    Dash,
    Input,
    Output,
    State,
    dcc,
    html,
    ctx,
    no_update,
)
from dash_auth import BasicAuth, check_groups

# Bootstrap 5.3 (Bootswatch "Cyborg" dark theme) is vendored in assets/
# so the app stays styled even on a local network without internet.
from flask import Flask, redirect, request
from tinydb import Query, TinyDB

# Create Flask server
server = Flask(__name__)
# Create Dash application and pass Flask server as argument
app = Dash(
    server=server,
    suppress_callback_exceptions=True,
)
app.title = "Cyber Elephant Bank"

dbname = "db.json"

# Serialise all DB mutations. TinyDB is not concurrency-safe and a transfer is a
# multi-step read-modify-write, so overlapping requests could corrupt balances.
# RLock lets db_reset -> db_init -> do_transfer re-enter on the same thread.
_db_lock = RLock()

# Initial name / password configuration
# For login, uppercase matter.
# Password convention: first 8 hex chars of the SHA-256 digest of the login
# name — reproducible, no list to store or distribute:
#   hashlib.sha256("Silence".encode()).hexdigest()[:8] == "6c61fe49"
# Change a player's password by editing the value below (or the recipe).
USER_PWD = {
    "Silence": "6c61fe49",
    "Zap": "7305f7d7",
    "Sudo": "a8929bfc",
    "Prof": "a761aecc",
    "Apache": "87ec4027",
    "Vigie": "112191d8",
    "Glock": "9c34760b",
    "Sabre": "a12a3115",
    "Boston": "a06522bc",
    "Diamond": "b639c243",
    "Yojimbo": "afc305d8",
    "Jab": "ba93802c",
    "Surin": "f54d3b2b",
    "Noise": "9ada8e83",
    "Tank": "c0b21fb1",
    "Strat": "cf117866",
    "Pixie Trust": "f2848eda",
    "Maverick": "1aadcb76",
    "Wasp": "74b9841a",
    "Bank": "676c471b",
}
### Auth stuff ###
BasicAuth(
    app,
    USER_PWD,
    secret_key="cyber_elephant",
    user_groups={
        "Maverick": ["admin"],
        "Bank": ["admin"],
        "Pixie Trust": ["admin"],
        "Wasp": ["admin"],
    },
)


# Logout landing: the Déconnexion button sends a deliberately WRONG login
# (logout:wrongpass) so the browser discards its cached pair. That request
# comes in as a 401 — bounce it back to the clean URL (no embedded userinfo)
# so the browser re-prompts with the normal login dialog instead of never
# letting the next user in.
@server.after_request
def _logout_redirect(response):
    if response.status_code == 401 and request.args.get("logout") == "1":
        clean = request.host_url.rstrip("/") + request.path
        return redirect(clean, code=302)
    return response


def norm(username):
    """
    Normalise name to avoid upper case / lower case / space issues
    """
    if not isinstance(username, str):
        username = "_INVALID_"
    return username.lower().strip()


VALID_USERS = [norm(u) for u in USER_PWD.keys()]


def display_name(normed):
    """
    Map a normalised name back to its display form ("maverick" -> "Maverick").
    The bank keeps its name "PNJs MDJ"; unknown names (NPC, __history__...)
    fall back to the raw value.
    """
    for name in USER_PWD:
        if norm(name) == normed:
            if norm(name) == "bank":
                return "PNJs MDJ"
            return name
    return normed


# 5-character account IDs (letters + digits, e.g. "32BGR"). Players type
# these instead of names; they are also shown in the header banner so each
# player knows their own ID. Typing is case-insensitive (auto-uppercased).
BANK_IDS = {
    "bank": "0PNJ0",
    "silence": "32BGR",
    "zap": "40AZE",
    "sudo": "83XDF",
    "prof": "94POT",
    "apache": "74UYT",
    "vigie": "86LKD",
    "glock": "25KQN",
    "sabre": "39SPQ",
    "boston": "12NCZ",
    "diamond": "70AND",
    "yojimbo": "30MBO",
    "jab": "14EKG",
    "surin": "66SXF",
    "noise": "50MPT",
    "tank": "36ECV",
    "strat": "24FRD",
    "pixie trust": "65OKN",
    "maverick": "15QZS",
    "wasp": "49YUP",
}
# bank number -> normalised user name
ID_TO_USER = {bid: name for name, bid in BANK_IDS.items()}
# bank number -> display name, for the admin dropdown labels
ID_TO_DISPLAY = {bid: display_name(name) for name, bid in BANK_IDS.items()}

# Admin dropdown targets: every account except the bank's own.
ADMIN_TARGETS = [
    {"label": f"{ID_TO_DISPLAY[bid]} — {bid}", "value": bid}
    for bid in ID_TO_USER
    if ID_TO_USER[bid] != "bank"
]


# Init balances per account. The bank funds every account at init (its
# own doc starts at 4 019 850 = 1 000 000 + all player balances), so after
# db_init the treasury holds exactly 1 000 000, as in the game table.
INIT_BALANCES = {
    "bank": 4_019_850,
    "silence": 2400,
    "zap": 2000,
    "sudo": 1800,
    "prof": 1600,
    "apache": 1200,
    "vigie": 1500,
    "glock": 1200,
    "sabre": 1500,
    "boston": 800,
    "diamond": 1600,
    "yojimbo": 1100,
    "jab": 1300,
    "surin": 750,
    "noise": 300,
    "tank": 200,
    "strat": 600,
    "pixie trust": 1_000_000,
    "maverick": 1_000_000,
    "wasp": 1_000_000,
}


# Set default value
def get_init_balance(username):
    """
    Initial value per user
    """
    return INIT_BALANCES.get(norm(username), 0)


def is_valid_name(name):
    """
    Check if name is a valid user
    """
    return norm(name) in VALID_USERS


def add(lhs, rhs):
    return lhs + rhs


def sub(lhs, rhs):
    return lhs - rhs


def _exec_op(qry_name, from_name, to, amount, op):
    """
    Helper function to avoid repeating code during transaction.
    Must be called under _db_lock.
    """
    User = Query()
    with TinyDB(dbname) as db:
        qry = User.name == qry_name
        res = db.search(qry)
        balance = res[0]["balance"]
        balance = op(balance, amount)

        history = res[0]["history"]
        history.append({"from": from_name, "to": to, "amount": amount, "when": time()})

        output = {"balance": balance, "history": history}
        db.update(output, qry)


def append_admin_note(admin_name, target, amount):
    """
    Log an admin panel action (send/take) in the admin user's own history so
    it shows up in the admin's view. Does not change any balance.
    Skipped when the admin is a party to the transfer (bank or target): the
    real transaction row already appears in that account's history and the
    note would render as a visible duplicate.
    Must be called under _db_lock.
    """
    if admin_name == "bank" or admin_name == target:
        return
    User = Query()
    with TinyDB(dbname) as db:
        qry = User.name == admin_name
        res = db.search(qry)
        history = res[0]["history"]
        history.append(
            {
                "from": "bank" if amount > 0 else target,
                "to": target if amount > 0 else "bank",
                "amount": abs(amount),
                "when": time(),
                "admin": admin_name,
            }
        )
        db.update({"history": history}, qry)


def update_global_history(from_name, to, amount):
    """
    The __history__ contains the history of all transaction (for easy access).
    Must be called under _db_lock.
    """

    User = Query()
    with TinyDB(dbname) as db:
        qry = User.name == "__history__"
        res = db.search(qry)
        history = res[0]["history"]
        history.append({"from": from_name, "to": to, "amount": amount, "when": time()})
        db.update({"history": history}, qry)


def do_transfer(from_name, to, amount, insufficient_msg=None):
    """
    Do a bank transfer.

    The whole check-and-write runs under _db_lock so the balance check and the
    debit/credit are atomic (no TOCTOU overdraft, no interleaved writes).
    Negative/zero amounts are rejected here; admin and bank (NPC) operations
    always call with a positive amount and pick direction via from/to.
    insufficient_msg overrides the "not enough money" message (used by the
    admin panel, which talks about "ce compte" instead of "vous").
    """
    with _db_lock:
        balance = get_current_balance(from_name)
        if not is_valid_name(to):
            return "Destinataire invalide"
        if not isinstance(amount, int) or amount <= 0:
            return "Montant impossible. Sélectionnez un entier positif."
        if amount > balance:
            if insufficient_msg:
                return insufficient_msg
            if from_name == "bank":
                return "Montant impossible. La banque n'a pas assez d'argent."
            return "Montant impossible. Vous n'avez pas assez d'argent."
        amount = int(amount)

        print(f"begin do_transfer({from_name}, {to}, {amount})")
        _exec_op(from_name, from_name, to, amount, sub)
        _exec_op(to, from_name, to, amount, add)
        update_global_history(from_name, to, amount)
    return None


def get_current_balance(username):
    """
    Return current balance
    """
    User = Query()
    with TinyDB(dbname) as db:
        user = db.search(User.name == username)[0]
        return int(user["balance"])


### Init and reset databse
def db_init():
    """
    Initialise database. Do nothing if databse already contains element
    """

    with _db_lock, TinyDB(dbname) as db:
        if len(db.all()) == 0:
            db.insert({"name": "__history__", "balance": 0, "history": []})
            db.insert(
                {"name": "bank", "balance": get_init_balance("bank"), "history": []}
            )
            for user in VALID_USERS:
                if user == "bank":
                    # The bank's own doc was inserted above; skipping it avoids
                    # creating a duplicate bank account with a self-transfer.
                    continue
                amount = get_init_balance(user)
                db.insert({"name": user, "balance": 0, "history": []})
                do_transfer("bank", user, amount)


def db_reset():
    """
    Reset database
    """

    with _db_lock:
        with TinyDB(dbname) as db:
            db.truncate()
        db_init()


### Layout section ###
def id_or_name(normed):
    """
    History display: characters appear as their 5-digit account number, the
    bank keeps its name, unknown/NPC names fall back to their raw form.
    """
    key = norm(normed)
    if key == "bank" or key not in BANK_IDS:
        return display_name(key)
    return BANK_IDS[key]


def party_label(normed):
    """
    Admin-ledger display: "Name (ID)", e.g. "Prof (94POT)" — the admin
    panel shows real names next to the account ID.
    """
    key = norm(normed)
    return f"{display_name(key)} ({BANK_IDS[key]})"


def make_history_table(username, show_inter=True):
    """
    Make the history as a mobile-friendly list of cards.
    Admins see the whole bank ledger (every transfer, from the global
    history): transfers between two players are tinted purple and can be
    filtered out (show_inter=False). Everyone else sees their own history.
    """
    ts = time()

    val = 0
    if username == "bank":
        # Bank do not start at 0
        val = get_init_balance(username)

    User = Query()
    with TinyDB(dbname) as db:
        if check_groups(["admin"]):
            # Admin ledger: all transfers + the "Admin" tag on operations
            # made through the admin panel (matched against own-history notes).
            global_hist = db.search(User.name == "__history__")[0]["history"]
            own_hist = db.search(User.name == username)[0]["history"]
            admin_notes = {
                (r["from"], r["to"], int(r["amount"])): int(r["when"])
                for r in own_hist
                if r.get("admin") == username
            }
            history = []
            for r in global_hist:
                key = (r["from"], r["to"], int(r["amount"]))
                tagged = key in admin_notes and abs(
                    int(r["when"]) - admin_notes[key]
                ) < 10
                history.append((r, tagged))
        else:
            history = [
                (r, False) for r in db.search(User.name == username)[0]["history"]
            ]

    transactions = []
    for row, row_admin in history:
        when = row.get("when")
        if when:
            when = strftime("%d/%m %H:%M", localtime(int(when)))
        else:
            when = ""
        if row_admin:
            # Admin panel action: no balance effect for the viewer, signed.
            transactions.append(
                [row["from"], row["to"], row["amount"], None, when, "admin"]
            )
        elif username == row["from"]:
            val = val - int(row["amount"])
            transactions.append([row["from"], row["to"], row["amount"], val, when])
        elif username == row["to"]:
            val = val + int(row["amount"])
            transactions.append([row["from"], row["to"], row["amount"], val, when])
        elif row.get("admin") == username:
            # Legacy admin note without a matching ledger row.
            transactions.append(
                [row["from"], row["to"], row["amount"], None, when, "admin"]
            )
        elif row["from"] != "bank" and row["to"] != "bank":
            # Transfer between two players: visible only to admins, filterable.
            if show_inter is False:
                continue
            transactions.append(
                [row["from"], row["to"], row["amount"], None, when, "inter"]
            )
        else:
            # Bank-related row (bank <-> someone) the viewer is not a party to.
            transactions.append(
                [row["from"], row["to"], row["amount"], None, when, "bank"]
            )

    you = id_or_name(username)

    def make_line(t):
        """
        Helper function to format a transaction row as a card
        """
        kind = t[5] if len(t) > 5 else "party"
        if kind == "admin":
            # Admin panel action (send/take): the admin is not a party, so
            # there is no balance effect for the viewer.
            from_name, to, amount, balance, when = t[0], t[1], t[2], None, t[4]
            party_from, party_to = party_label(from_name), party_label(to)
            if to == "bank":
                amount_str, color, prefix = f"-{amount}", "danger", "Admin"
            else:
                amount_str, color, prefix = f"+{amount}", "success", "Admin"
            line_class = "txn-line"
        elif kind == "inter":
            # Transfer between two players (admin view): purple, no balance.
            from_name, to, amount, balance, when = t[0], t[1], t[2], None, t[4]
            party_from, party_to = party_label(from_name), party_label(to)
            amount_str, color, prefix = f"{amount}", None, "Joueurs"
            line_class = "txn-line txn-line-inter"
        elif kind == "bank":
            # Bank-related row the viewer is not a party to.
            from_name, to, amount, balance, when = t[0], t[1], t[2], None, t[4]
            party_from, party_to = party_label(from_name), party_label(to)
            if to == "bank":
                amount_str, color, prefix = f"+{amount}", "success", "Banque"
            else:
                amount_str, color, prefix = f"-{amount}", "danger", "Banque"
            line_class = "txn-line"
        else:
            from_name, to, amount, balance, when = t[0], t[1], t[2], t[3], t[4]
            from_disp, to_disp = id_or_name(from_name), id_or_name(to)

            if from_name == username:
                party_from, party_to = f"{you} (vous)", to_disp
            elif to == username:
                party_from, party_to = from_disp, f"{you} (vous)"
            else:
                party_from, party_to = from_disp, to_disp

            if to == username:
                amount_str, color, prefix = f"+{amount}", "success", "Reçu de"
            else:
                amount_str, color, prefix = f"-{amount}", "danger", "Envoyé à"
            line_class = "txn-line"

        if kind == "inter":
            meta = [html.Span(amount_str, className="txn-amount txn-inter")]
        else:
            meta = [html.Span(amount_str, className=f"txn-amount text-{color}")]
        if balance is not None:
            meta.append(html.Span(f"· solde {balance}", className="txn-balance"))
        if when:
            meta.append(html.Span(when, className="txn-time"))

        return dbc.ListGroupItem(
            [
                html.Div(
                    [
                        html.Span(prefix, className="txn-prefix"),
                        html.Span(
                            f"{party_from} → {party_to}", className="txn-parties"
                        ),
                    ],
                    className=line_class,
                ),
                html.Div(meta, className="txn-meta"),
            ]
        )

    rows = []
    for t in reversed(transactions):
        rows.append(make_line(t))

    te = time()
    print("func:%r took: %2.4f ms" % ("make_history_table", (te - ts) * 1000.0))
    return dbc.ListGroup(rows, flush=True, className="history-list"), val


def build_public_balances():
    """
    Total credits of every account (characters + bank) as chips. Admin-only:
    rendered only when the viewer is in the admin group.
    """
    chips = []
    for name in VALID_USERS:
        b = get_current_balance(name)
        chips.append(
            html.Div(
                [
                    html.Span(display_name(name), className="cb-name"),
                    html.Span(f"({BANK_IDS[name]})", className="cb-id"),
                    html.Span(
                        f"{b:,}".replace(",", " "), className="cb-bal"
                    ),
                ],
                className="credit-chip",
            )
        )
    return chips


def admin_panel():
    """
    Simplified admin panel: pick a character in the dropdown, enter a signed
    amount (negative = take money FROM that character), validate.
    """
    reset_row = dbc.Row(
        [
            dbc.Col(html.H5("Actions", className="mb-0"), width="auto"),
            dbc.Col(
                dbc.Button(
                    "RESET DATABASE",
                    color="danger",
                    className="me-1",
                    id="admin-reset-db",
                ),
                width="auto",
            ),
            html.Div(id="output-danger"),
        ],
        className="justify-content-between align-items-center g-0 mb-2",
    )

    return html.Div(
        [
            dbc.Alert(
                "",
                id="admin-msg",
                dismissable=False,
                is_open=False,
                color="success",
            ),
            reset_row,
            dcc.ConfirmDialog(
                id="confirm-danger",
                message="Danger ! This is irreversible. Are you sure you want to continue ?",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dcc.Dropdown(
                            id="admin-target",
                            options=ADMIN_TARGETS,
                            placeholder="Compte",
                            clearable=False,
                            searchable=True,
                        ),
                        width=7,
                    ),
                    dbc.Col(
                        dcc.Input(
                            id="admin-amount",
                            placeholder="Montant (±)",
                            type="text",
                            inputMode="text",
                            pattern="-?[0-9]*",
                            className="transfer-input",
                        ),
                        width=5,
                    ),
                ],
                className="g-2 transfer-row mt-2",
            ),
            dbc.Button(
                "Envoyer / Prélever",
                color="primary",
                id="admin-do-transfer",
                size="lg",
                className="transfer-btn w-100 mt-2",
            ),
            html.Div(
                "Montant négatif = prélever de l'argent sur ce compte.",
                className="admin-hint",
            ),
            html.Div(id="admin-balance", className="admin-balance"),
        ]
    )


def page_header():
    """
    Sticky top header: balance banner (the main info) + current user,
    always visible while scrolling
    """
    return html.Div(
        [
            html.Span("🦾 Cyber Elephant Bank", className="app-title"),
            html.Div(
                [
                    html.Span(id="name", className="app-username"),
                    html.Div(id="balance", className="balance-value"),
                    html.Button(
                        "Déconnexion",
                        id="logout-btn",
                        className="logout-btn",
                        title="Se déconnecter (afficher l'écran de connexion)",
                    ),
                    # Hidden: sink for the logout click callback.
                    html.Div(id="logout-feedback", hidden=True),
                ],
                className="app-header-balance",
            ),
        ],
        className="app-header",
    )


def page_footer():
    """
    Sticky bottom action bar: transfer form always thumb-reachable.
    Destination is the 5-digit bank account number, not a name.
    """
    # Collapsed for admin users: the admin panel's dropdown + signed amount
    # replaces the standard player transfer form (it would be redundant).
    return dbc.Collapse(
        html.Div(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            dcc.Input(
                                id="transfer-id",
                                placeholder="ID (ex: 32BGR)",
                                type="text",
                                inputMode="text",
                                pattern="[A-Za-z0-9]{5}",
                                maxLength=5,
                                className="transfer-input",
                            ),
                            width=7,
                        ),
                        dbc.Col(
                            dcc.Input(
                                id="transfer-amount",
                                placeholder="Montant",
                                type="text",
                                inputMode="numeric",
                                pattern="[0-9]*",
                                className="transfer-input",
                            ),
                            width=5,
                        ),
                    ],
                    className="g-2 transfer-row",
                ),
                dbc.Button(
                    "Transfer",
                    color="success",
                    id="do-transfer",
                    size="lg",
                    className="transfer-btn w-100",
                ),
            ],
            className="app-footer",
        ),
        id="player-transfer",
        is_open=True,
    )


# Special case for admin
layout = [
    page_header(),
    dbc.Alert(
        "Erreur.",
        id="err-msg",
        dismissable=False,
        is_open=False,
        color="danger",
        className="mt-2",
    ),
    # Admin-only board: the total credits of every account. Players never
    # see the section (Collapse kept closed for non-admin users).
    dbc.Collapse(
        html.Div(
            [
                html.H5("Comptes", className="mt-1"),
                html.Div(id="public-balances", className="credit-grid"),
            ],
            className="app-content",
        ),
        id="balances-section",
        is_open=False,
    ),
    html.Div(
        [
            html.H5("Historique", className="mt-1"),
            dbc.Collapse(
                dbc.Switch(
                    id="show-inter",
                    label="Afficher les transferts entre joueurs",
                    value=True,
                ),
                id="inter-filter",
                is_open=False,
            ),
            html.Div(id="history_table"),
            dbc.Collapse(
                dbc.Button(
                    "🛠 Administration",
                    id="admin-toggle",
                    color="secondary",
                    className="admin-toggle w-100",
                ),
                id="admin-toggle-wrap",
                is_open=False,
            ),
            dbc.Collapse(admin_panel(), id="admin-panel", is_open=True),
        ],
        className="app-content",
    ),
    page_footer(),
]

app.layout = html.Div(
    [
        html.Div(id="output", children=layout),
        dcc.Location(id="url", refresh=False),
        # Set by admin_transfer after every successful send/take: it chains
        # the view refresh AFTER the transfer write (no stale history read).
        dcc.Store(id="admin-op", data=None),
    ],
    className="container app-root",
)
### End layout section ###

# Logout: BasicAuth credentials live in the browser, so the server cannot
# clear them. Instead, navigate to the same origin with deliberately wrong
# credentials (logout:wrongpass + ?logout=1): the server answers 401 and
# bounces back to the clean URL (see _logout_redirect), which drops the
# browser's cached pair and shows the login dialog again.
app.clientside_callback(
    """
    function(n) {
        if (!n) return "";
        var loc = window.location;
        window.location.href = loc.protocol + "//logout:wrongpass@" + loc.host + loc.pathname + "?logout=1";
        return "";
    }
    """,
    Output("logout-feedback", "children"),
    Input("logout-btn", "n_clicks"),
    prevent_initial_call=True,
)


@app.callback(
    Output("confirm-danger", "displayed"), Input("admin-reset-db", "n_clicks"), groups=["admin"]
)
def display_confirm(value):
    if value:
        return True
    return False


@app.callback(
    Output("output-danger", "children"),
    Input("confirm-danger", "submit_n_clicks"),
    groups=["admin"],
)
def update_output(submit_n_clicks):
    if submit_n_clicks:
        db_reset()
        return "It wasnt easy but we did it : database has been RESET"


@app.callback(
    [
        Output(component_id="name", component_property="children"),
        Output(component_id="balance", component_property="children"),
        Output(component_id="history_table", component_property="children"),
        Output(component_id="err-msg", component_property="children"),
        Output(component_id="err-msg", component_property="is_open"),
        Output(component_id="admin-panel", component_property="is_open"),
        Output(component_id="transfer-id", component_property="value"),
        Output(component_id="transfer-amount", component_property="value"),
        Output(component_id="player-transfer", component_property="is_open"),
        Output(component_id="public-balances", component_property="children"),
        Output(component_id="inter-filter", component_property="is_open"),
        Output(component_id="admin-toggle-wrap", component_property="is_open"),
        Output(component_id="admin-toggle", component_property="children"),
        # The Comptes board (total credits) is visible to admins only.
        Output(component_id="balances-section", component_property="is_open"),
    ],
    [
        Input(component_id="do-transfer", component_property="n_clicks"),
        Input(component_id="transfer-amount", component_property="n_submit"),
        # Fired by the admin callback AFTER its DB write completes (see
        # dcc.Store "admin-op"), so the refresh always reads fresh data.
        Input(component_id="admin-op", component_property="data"),
        # Admin-only toggle: hide/show inter-player transfers in the ledger.
        Input(component_id="show-inter", component_property="value"),
        # Admin-only toggle: collapse/expand the admin panel (click parity).
        Input(component_id="admin-toggle", component_property="n_clicks"),
    ],
    [
        State(component_id="url", component_property="pathname"),
        State(component_id="transfer-id", component_property="value"),
        State(component_id="transfer-amount", component_property="value"),
    ],
)
def update_output_div(
    n_clicks, n_submit_amount, admin_op, show_inter, admin_toggle_clicks,
    pathname, transfer_id, transfer_amount,
):
    """
    Trigger on page load, on player transfer (button or Enter), or after an
    admin send/take (chained through the admin-op store so this refresh runs
    only after the transfer is committed to the DB). Return the updates.
    """
    username = norm(request.authorization["username"])

    err_msg = ""
    err_msg_open = False
    clear_id = no_update
    clear_amount = no_update
    if ctx.triggered_id in ("do-transfer", "transfer-amount"):
        if transfer_id is None and transfer_amount is None:
            pass
        elif transfer_id is None or transfer_amount is None:
            err_msg = "Destinataire ou montant manquant."
        else:
            # Resolve the account ID (5 chars, letters + digits, typed case-
            # insensitively). The bank's account (0PNJ0) IS a valid player
            # destination: anyone can send credits to the treasury.
            target = ID_TO_USER.get(str(transfer_id).strip().upper())
            if target is None:
                err_msg = "Numéro de compte invalide."
            elif username == target:
                err_msg = "Tu ne peux pas te designer comme destinataire."
            else:
                # Non-integer amounts (e.g. "12.5") are rejected here, never
                # rounded: do_transfer itself also refuses anything not an int.
                try:
                    transfer_amount = int(transfer_amount)
                except (TypeError, ValueError):
                    err_msg = "Montant invalide : entier positif requis."
                else:
                    print(f"perform transfer({transfer_id}, {transfer_amount})")
                    err_msg = do_transfer(username, target, transfer_amount)
        clear_id, clear_amount = None, ""

    if err_msg:
        err_msg_open = True

    history_table, curr_balance = make_history_table(username, show_inter)
    balance = get_current_balance(username)
    # # Check history and amount are coherent, if not use stored value
    if curr_balance != balance:
        curr_balance = balance

    is_admin = False
    if check_groups(["admin"]):
        is_admin = True
    # Admin panel collapsed/expanded by clicks on the toggle (click parity:
    # 0, 2, 4... = open, 1, 3... = closed; back to open on page reload).
    admin_open = is_admin and (admin_toggle_clicks or 0) % 2 == 0

    return [
        [
            display_name(username),
            html.Span(f"({BANK_IDS[username]})", className="app-id"),
        ],
        html.Div(
            [
                html.Span("🪙", className="balance-icon"),
                html.Span(
                    f"{balance:,}".replace(",", " "), className="balance-num"
                ),
                html.Span("crédits", className="balance-unit"),
            ],
            className="balance-value",
        ),
        history_table,
        err_msg,
        err_msg_open,
        admin_open,  # admin panel visible (unless collapsed by the toggle)
        clear_id,
        clear_amount,
        not is_admin,  # admin users don't see the standard transfer form
        [] if not is_admin else build_public_balances(),
        is_admin,  # the inter-player filter switch is shown to admins only
        is_admin,  # the admin panel collapse toggle is shown to admins only
        [
            "🛠 Administration",
            html.Span("▾" if admin_open else "▸", className="admin-toggle-caret"),
        ],
        is_admin,  # the Comptes board (total credits) is admin-only
    ]


@app.callback(
    [
        Output("admin-msg", "children"),
        Output("admin-msg", "is_open"),
        Output("admin-target", "value"),
        Output("admin-amount", "value"),
        # Chained refresh trigger: bump the store so update_output_div runs
        # only after the transfer + admin note are committed to the DB.
        Output("admin-op", "data"),
    ],
    Input("admin-do-transfer", "n_clicks"),
    [
        State("admin-target", "value"),
        State("admin-amount", "value"),
    ],
    groups=["admin"],
    prevent_initial_call=True,
)
def admin_transfer(n_clicks, target_id, raw_amount):
    """
    Simplified admin action: pick the account in the dropdown, enter a signed
    amount. Positive = send bank money TO the account (the bank cannot go
    below 0). Negative = take money FROM the account (it cannot go below 0).
    """
    if not check_groups(["admin"]):
        return "Accès refusé.", True, no_update, no_update, no_update

    username = norm(request.authorization["username"])
    target = ID_TO_USER.get(str(target_id).strip().upper()) if target_id else None
    if target is None:
        return "Compte invalide.", True, no_update, no_update, no_update

    # Strict integer parse (accepts "-150"); reject 0 and anything else.
    if isinstance(raw_amount, float) and raw_amount.is_integer():
        raw_amount = int(raw_amount)
    else:
        try:
            raw_amount = int(str(raw_amount).strip())
        except (TypeError, ValueError):
            raw_amount = None
    if raw_amount is None or raw_amount == 0:
        return "Montant invalide : entier non nul requis.", True, no_update, no_update, no_update

    if raw_amount > 0:
        err = do_transfer("bank", target, raw_amount)
        if err:
            return err, True, no_update, no_update, no_update
        append_admin_note(username, target, raw_amount)
        msg = (
            f"{raw_amount} crédit(s) envoyé(s) à "
            f"{display_name(target)} ({BANK_IDS[target]})."
        )
    else:
        err = do_transfer(
            target,
            "bank",
            -raw_amount,
            insufficient_msg="Montant impossible. Ce compte n'a pas assez d'argent.",
        )
        if err:
            return err, True, no_update, no_update, no_update
        append_admin_note(username, target, raw_amount)
        msg = (
            f"{-raw_amount} crédit(s) prélevé(s) sur "
            f"{display_name(target)} ({BANK_IDS[target]})."
        )

    return msg, True, None, "", {"ts": time()}


@app.callback(
    Output("admin-balance", "children"),
    Input("admin-target", "value"),
    groups=["admin"],
    prevent_initial_call=True,
)
def admin_target_balance(target_id):
    """
    Show the selected account's current balance inside the admin panel
    (the Comptes board is admin-only, this avoids a manual lookup).
    """
    target = ID_TO_USER.get(str(target_id).strip().upper()) if target_id else None
    if target is None:
        return ""
    return f"Solde actuel : {get_current_balance(target):,} crédits".replace(",", " ")


### End allback section ###

# Hosting: gunicorn imports this module without running __main__, so seed
# the database on first boot (db_init is a no-op if the db already exists).
if not os.path.exists(dbname):
    db_init()


if __name__ == "__main__":
    db_init()
    # Change that as needed
    app.run_server(host="192.168.1.42", port=36050, debug=True)
    # app.run_server(host="127.0.0.1", port=36050, debug=True)

