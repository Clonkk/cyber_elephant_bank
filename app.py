from threading import RLock
from time import localtime, strftime, time

import dash_bootstrap_components as dbc
from dash import (
    ALL,
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
from flask import Flask, request
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
# For login, uppercase matter
USER_PWD = {
    "Sinistre": "123",
    "Prof": "123",
    "Pixie": "456",
    "Maverick": "456",
    "Bank": "bank",
}
### Auth stuff ###
BasicAuth(
    app,
    USER_PWD,
    secret_key="cyber_elephant",
    user_groups={"Maverick": ["admin"], "Bank": ["admin"], "Pixie": ["admin"]},
)


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
    Fall back to the raw value for unknown names (NPC, __history__...).
    """
    for name in USER_PWD:
        if norm(name) == normed:
            return name
    return normed

# Transfer targets: everyone except the bank. The dcc.Dropdown keeps the
# original label (e.g. "Pixie") but submits the normalised value.
TRANSFER_TARGETS = [
    {"label": u, "value": norm(u)} for u in USER_PWD.keys() if norm(u) != "bank"
]


# Set default value
def get_init_balance(username):
    """
    Initial value per user
    """
    match norm(username):
        case "bank":
            return 10_000_000

        case "sinistre":
            return 1500

        case "prof":
            return 700

        case "pixie":
            return 50_000

        case "maverick":
            return 50_000

        case _:
            return 0


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


def do_transfer(from_name, to, amount):
    """
    Do a bank transfer.

    The whole check-and-write runs under _db_lock so the balance check and the
    debit/credit are atomic (no TOCTOU overdraft, no interleaved writes).
    Negative/zero amounts are rejected here; admin and bank (NPC) operations
    always call with a positive amount and pick direction via from/to.
    """
    with _db_lock:
        balance = get_current_balance(from_name)
        if not is_valid_name(to):
            return "Destinataire invalide"
        if not isinstance(amount, int) or amount <= 0:
            return "Montant impossible. Sélectionnez un entier positif."
        if amount > balance:
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
def make_history_table(username):
    """
    Make the history as a mobile-friendly list of cards
    """
    ts = time()

    val = 0
    if username == "bank":
        # Bank do not start at 0
        val = get_init_balance(username)

    User = Query()
    with TinyDB(dbname) as db:
        history = db.search(User.name == username)[0]["history"]

    transactions = []
    for row in history:
        when = row.get("when")
        if when:
            when = strftime("%d/%m %H:%M", localtime(int(when)))
        else:
            when = ""
        if username == row["from"]:
            val = val - int(row["amount"])
            transactions.append([row["from"], row["to"], row["amount"], val, when])
        elif username == row["to"]:
            val = val + int(row["amount"])
            transactions.append([row["from"], row["to"], row["amount"], val, when])

    you = display_name(username)

    def make_line(t):
        """
        Helper function to format a transaction row as a card
        """
        from_name, to, amount, balance, when = t[0], t[1], t[2], t[3], t[4]
        from_disp, to_disp = display_name(from_name), display_name(to)

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

        meta = [
            html.Span(amount_str, className=f"txn-amount text-{color}"),
            html.Span(f"· solde {balance}", className="txn-balance"),
        ]
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
                    className="txn-line",
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


def admin_panel():
    reset_row = dbc.Row(
        [
            dbc.Col(html.H5("Administration", className="mb-0"), width="auto"),
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

    rows = []
    admin_msgs = []
    with TinyDB(dbname) as db:
        for row in db:
            if row["name"] in ["bank", "__history__"]:
                continue

            name = row["name"]
            balance = row["balance"]

            rows.append(
                html.Div(
                    [
                        dbc.Row(
                            [
                                dbc.Col(
                                    html.H6(name, className="mb-0"), width="auto"
                                ),
                                dbc.Col(
                                    html.H6(
                                        balance,
                                        id={
                                            "type": "admin-balance-info",
                                            "index": f"{name}",
                                        },
                                        className="mb-0",
                                    ),
                                    width="auto",
                                ),
                            ],
                            className="g-0 justify-content-between align-items-center",
                        ),
                        dbc.InputGroup(
                            [
                                dbc.Input(
                                    id={
                                        "type": "admin-transfer-amount",
                                        "index": f"{name}",
                                    },
                                    step=1,
                                    placeholder="Montant",
                                    type="number",
                                    value=0.0,
                                ),
                                dbc.Button(
                                    "Modifier solde",
                                    color="primary",
                                    outline=True,
                                    id={
                                        "type": "admin-do-transfer",
                                        "index": f"{name}",
                                    },
                                ),
                            ],
                            className="mt-2",
                        ),
                    ],
                    className="admin-row p-2 mb-2 rounded-3",
                )
            )
            admin_msgs.append(
                dbc.Alert(
                    f"Message pour {name}.",
                    id={
                        "type": "admin-msg",
                        "index": f"{name}",
                    },
                    dismissable=False,
                    is_open=False,
                    color="success",
                ),
            )

    layout = [
        html.Div(admin_msgs),
        reset_row,
        dcc.ConfirmDialog(
            id="confirm-danger",
            message="Danger ! This is irreversible. Are you sure you want to continue ?",
        ),
        html.Div(rows),
    ]
    return layout


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
                ],
                className="app-header-balance",
            ),
        ],
        className="app-header",
    )


def page_footer():
    """
    Sticky bottom action bar: transfer form always thumb-reachable
    """
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        dcc.Dropdown(
                            id="transfer-id",
                            options=TRANSFER_TARGETS,
                            placeholder="Destinataire",
                            clearable=True,
                            searchable=True,
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
    html.Div(
        [
            html.H5("Historique", className="mt-1"),
            html.Div(id="history_table"),
            dbc.Collapse(admin_panel(), id="admin-panel", is_open=False),
        ],
        className="app-content",
    ),
    page_footer(),
]

app.layout = html.Div(
    [
        html.Div(id="output", children=layout),
        dcc.Location(id="url", refresh=False),
    ],
    className="container app-root",
)
### End layout section ###


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
        Output(component_id="transfer-id", component_property="options"),
        Output(component_id="transfer-amount", component_property="value"),
    ],
    [
        Input(component_id="do-transfer", component_property="n_clicks"),
        Input(component_id="transfer-amount", component_property="n_submit"),
        Input(
            {"type": "admin-do-transfer", "index": ALL},
            component_property="n_clicks_timestamp",
        ),
    ],
    [
        State(component_id="url", component_property="pathname"),
        State(component_id="transfer-id", component_property="value"),
        State(component_id="transfer-amount", component_property="value"),
    ],
)
def update_output_div(
    n_clicks, n_submit_amount, n_clicks_timestamp_admin, pathname,
    transfer_id, transfer_amount,
):
    """
    Trigger when page load, when the transfer button is clicked, when Enter is
    pressed in one of the transfer fields, or after an admin balance change.
    Return the update component to display.
    """
    username = norm(request.authorization["username"])

    # Dropdown targets: everyone except the bank and the logged-in user
    transfer_targets = [o for o in TRANSFER_TARGETS if o["value"] != username]

    err_msg = ""
    err_msg_open = False
    clear_id = no_update
    clear_amount = no_update
    if ctx.triggered_id in ("do-transfer", "transfer-amount"):
        if transfer_id is None and transfer_amount is None:
            pass
        elif transfer_id is None or transfer_amount is None:
            err_msg = "Destinataire ou montant manquant."
        elif username == norm(transfer_id):
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
                err_msg = do_transfer(username, norm(transfer_id), transfer_amount)
        clear_id, clear_amount = None, ""

    if err_msg:
        err_msg_open = True

    history_table, curr_balance = make_history_table(username)
    balance = get_current_balance(username)
    # # Check history and amount are coherent, if not use stored value
    if curr_balance != balance:
        curr_balance = balance

    is_admin = False
    if check_groups(["admin"]):
        is_admin = True

    return [
        display_name(username),
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
        is_admin,
        clear_id,
        transfer_targets,
        clear_amount,
    ]


@app.callback(
    [
        Output(
            {"type": "admin-msg", "index": ALL},
            "is_open",
            allow_duplicate=True,
        ),
        Output(
            {"type": "admin-msg", "index": ALL},
            "children",
            allow_duplicate=True,
        ),
        Output(
            {"type": "admin-balance-info", "index": ALL},
            "children",
            allow_duplicate=True,
        ),
    ],
    [
        Input(
            {"type": "admin-do-transfer", "index": ALL},
            component_property="n_clicks_timestamp",
        ),
    ],
    [
        State({"type": "admin-transfer-amount", "index": ALL}, "value"),
        State(
            {"type": "admin-msg", "index": ALL},
            "is_open",
        ),
        State(
            {"type": "admin-msg", "index": ALL},
            "children",
        ),
        State(
            {"type": "admin-balance-info", "index": ALL},
            "children",
        ),
    ],
    groups=["admin"],
    prevent_initial_call=True,
)
def update_user_balance(
    n_clicks, amounts, is_open_lst, admin_msg_lst, admin_balance_lst
):
    def f(x):
        if x:
            return x
        return 0

    username = ctx.triggered_id["index"]
    n_clicks = [f(n) for n in n_clicks]
    amounts = [f(a) for a in amounts]
    index = max(enumerate(n_clicks), key=lambda x: x[1])[0]

    is_open_lst = [False] * len(is_open_lst)
    if not check_groups(["admin"]):
        admin_msg_lst = ["Unauthorized"] * len(is_open_lst)
        admin_balance_lst = ["-9999"] * len(is_open_lst)
        return [is_open_lst, admin_msg_lst, admin_balance_lst]

    # Strict integer check: a decimal like 12.5 must be rejected with a clear
    # message, never silently truncated (int(12.5) == 12) or crash (int("12.5")).
    raw = amounts[index]
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    if not isinstance(raw, int) or raw == 0:
        is_open_lst[index] = True
        admin_msg_lst[index] = (
            f"Montant invalide : '{raw}' n'est pas un entier non nul."
        )
        return [is_open_lst, admin_msg_lst, admin_balance_lst]
    amount = raw

    is_open_lst[index] = True
    if amount < 0:
        msg = (
            f"{abs(amount)} crédit(s) prélevé(s) du compte '{username}' par la banque."
        )
        do_transfer(username, "bank", abs(amount))
    else:
        msg = f"{abs(amount)} crédit(s) ajouté(s) au compte '{username}' par la banque."
        do_transfer("bank", username, abs(amount))

    admin_msg_lst[index] = msg
    balance = get_current_balance(username)
    admin_balance_lst[index] = balance
    return [is_open_lst, admin_msg_lst, admin_balance_lst]


### End allback section ###

if __name__ == "__main__":
    db_init()
    # Change that as needed
    # app.run_server(host="192.168.1.130", port=36050, debug=True)
    app.run_server(host="127.0.0.1", port=36050, debug=True)

