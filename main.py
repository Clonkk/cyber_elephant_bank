from time import time

import dash_bootstrap_components as dbc
from dash import (
    Dash,
    Input,
    Output,
    State,
    ctx,
    dcc,
    html,
)
from dash_auth import BasicAuth

# Read more about DBC
from flask import Flask, request
from tinydb import Query, TinyDB

# Can download stylesheet from internet
# external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
# Create Flask server
# Create Dash application and pass Flask server as argument
server = Flask(__name__)  # necessary for video stream, which uses flask stream
app = Dash(
    server=server,
    # Download a CSS style
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
)

db = TinyDB("db.json")
User = Query()

# Initial name / password configuration
# For login, uppercase matter
USER_PWD = {
    "Sinistre": "123",
    "Prof": "123",
    "Pixie": "456",
    "Maverick": "456",
}
### Auth stuff ###
BasicAuth(
    app,
    USER_PWD,
    secret_key="cyber_elephant",
)


def norm(username):
    """
    Normalise name to avoid upper case / lower case / space issues
    """
    if not isinstance(username, str):
        username = "_INVALID_"
    return username.lower().strip()


VALID_USERS = [norm(u) for u in USER_PWD.keys()]
ADMIN_USERS = [norm("Maverick"), norm("Pixie"), norm("bank")]


# Set default value
def get_init_balance(username):
    """
    Initial value per user
    """
    match norm(username):
        case "sinistre":
            return 1500

        case "prof":
            return 700

        case "pixie":
            return 50_000

        case "maverick":
            return 50_000


def is_valid_name(name):
    """
    Check if name is a valid user
    """
    if norm(name) in VALID_USERS:
        return True
    return False


def add(lhs, rhs):
    return lhs + rhs


def sub(lhs, rhs):
    return lhs - rhs


def _exec_op(qry_name, from_name, to, amount, op):
    """
    Helper function to avoid repeating code during transaction
    """
    qry = User.name == qry_name
    res = db.search(qry)
    balance = res[0]["balance"]
    balance = op(balance, amount)

    history = res[0]["history"]
    history.append({"from": from_name, "to": to, "amount": amount})

    output = {"balance": balance, "history": history}
    db.update(output, qry)


def update_global_history(from_name, to, amount):
    """
    The __history__ contains the history of all transaction (for easy access)
    """
    qry = User.name == "__history__"
    res = db.search(qry)
    history = res[0]["history"]
    history.append({"from": from_name, "to": to, "amount": amount})
    db.update({"history": history}, qry)


def do_transfer(from_name, to, amount):
    """
    Do a bank transfer
    """
    balance = get_current_balance(from_name)
    if not is_valid_name(to):
        return "Destinataire invalide"
    if not isinstance(amount, int) or amount > balance:
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
    user = db.search(User.name == username)[0]
    return int(user["balance"])


def make_history_table(username):
    """
    Make the history table per user
    """
    ts = time()

    table_header = [
        html.Thead(
            html.Tr(
                [
                    html.Th("From"),
                    html.Th("To"),
                    html.Th("Amount"),
                    html.Th("Balance"),
                ]
            )
        )
    ]

    transactions = []
    val = 0  # get_init_balance(username)
    history = db.search(User.name == username)[0]["history"]
    for row in history:
        if username == row["from"]:
            val = val - int(row["amount"])
            curr_row = [row["from"], row["to"], row["amount"], val]
            transactions.append(curr_row)
        elif username == row["to"]:
            val = val + int(row["amount"])
            curr_row = [row["from"], row["to"], row["amount"], val]
            transactions.append(curr_row)

    def make_line(t):
        """
        Helper function to format a transaction row in the history table
        """
        from_name, to, amount, balance = t[0], t[1], t[2], t[3]
        if from_name == username:
            from_name = from_name + " (me)"

        if to == username:
            to = to + " (me)"

        row = html.Tr(
            [html.Td(from_name), html.Td(to), html.Td(amount), html.Td(balance)]
        )
        return row

    rows = []
    for t in reversed(transactions):
        rows.append(make_line(t))

    table_body = [html.Tbody(rows)]
    table = dbc.Table(table_header + table_body, bordered=True)

    te = time()
    print("func:%r took: %2.4f ms" % ("make_history_table", (te - ts) * 1000.0))
    return table, val


### Init and reset databse
def db_init():
    """
    Initialise database. Do nothing if databse already contains element
    """
    if len(db.all()) == 0:
        db.insert({"name": "__history__", "balance": 0, "history": []})
        db.insert({"name": "bank", "balance": 1e7, "history": []})
        for user in VALID_USERS:
            amount = get_init_balance(user)
            db.insert({"name": user, "balance": 0, "history": []})
            do_transfer("bank", user, amount)


def db_reset():
    """
    Reset database
    """
    db.truncate()
    db_init()


### Layout section ###
ret = dbc.Row(
    [
        dbc.Col(
            [
                html.H6("Balance: ??????", id="balance"),
            ]
        ),
        dbc.Col(
            dbc.Row(
                [
                    dcc.Input(
                        id="transfer-id",
                        placeholder="destinataire",
                        type="text",
                    ),
                    dcc.Input(
                        id="transfer-amount",
                        min=0,
                        step=1,
                        placeholder=0.0,
                        type="number",
                    ),
                ]
            )
        ),
        dbc.Col([dbc.Button("Transfer", color="success", id="do-transfer", href="/")]),
    ]
)

# Special case for admin
layout = [
    html.Div("placeholder name", id="name"),
    html.Hr(),
    ret,
    dbc.Alert(
        "This is a danger alert. Scary!",
        id="err-msg",
        dismissable=False,
        is_open=False,
        color="danger",
    ),
    html.Hr(),
    html.H2("History"),
    html.Div(id="history_table"),
]

app.layout = html.Div(
    [
        html.Div(id="output", children=layout),
        dcc.Location(id="url", refresh=False),
    ],
    className="container",
)
### End layout section ###


@app.callback(
    [
        Output(component_id="name", component_property="children"),
        Output(component_id="balance", component_property="children"),
        Output(component_id="history_table", component_property="children"),
        Output(component_id="err-msg", component_property="children"),
        Output(component_id="err-msg", component_property="is_open"),
        Output(component_id="url", component_property="pathname"),
    ],
    [
        Input(component_id="do-transfer", component_property="n_clicks"),
    ],
    [
        State(component_id="url", component_property="pathname"),
        State(component_id="transfer-id", component_property="value"),
        State(component_id="transfer-amount", component_property="value"),
    ],
)
def update_output_div(n_clicks, pathname, transfer_id, transfer_amount):
    """
    Trigger when page load or when the transfer button is clicked.
    Return the update component to display.
    """
    username = request.authorization["username"]
    username = norm(username)

    # if username in ADMIN_USERS:
    #     return admin_panel(username)

    err_msg = ""
    err_msg_open = False
    # match ctx.triggered_id:
    if transfer_id is None and transfer_amount is None:
        pass
    elif username == norm(transfer_id):
        err_msg = "Tu ne peux pas te designer comme destinataire."
    else:
        print(f"perform transfer({transfer_id}, {transfer_amount})")
        err_msg = do_transfer(username, norm(transfer_id), transfer_amount)

    if err_msg:
        err_msg_open = True

    history_table, curr_balance = make_history_table(username)
    balance = get_current_balance(username)
    # Check history and amount are coherent, if not use stored value
    if curr_balance != balance:
        curr_balance = balance

    return [
        html.H2(username),
        curr_balance,
        history_table,
        err_msg,
        err_msg_open,
        pathname,
    ]


### End allback section ###

if __name__ == "__main__":
    db_init()
    app.run_server(host="192.168.1.130", port=36050, debug=True)
