import os
from functools import wraps
from time import time

import dash_bootstrap_components as dbc
from dash import (
    ctx,
    Dash,
    Input,
    Output,
    State,
    dcc,
    html,
)
from dash_auth import BasicAuth

# Read more about DBC
# https://dash-bootstrap-components.opensource.faculty.ai/examples/
# https://dash-bootstrap-components.opensource.faculty.ai/docs/
# https://dash-bootstrap-components.opensource.faculty.ai/docs/components/
from flask import Flask, request
from tinydb import Query, TinyDB


# Can download stylesheet from internet
#  external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
# Can use predefined dbc themes
external_stylesheets = [dbc.themes.BOOTSTRAP]

# Create Flask server
server = Flask(__name__)  # necessary for video stream, which uses flask stream
# Create Dash application and pass Flask server as argument
app = Dash(
    server=server,
    # Download a CSS style
    external_stylesheets=external_stylesheets,
    suppress_callback_exceptions=True,
)

# Prepare small db
db = TinyDB("db.json")
User = Query()
USER_PWD = {
    "sinistre": "123",
    "prof": "123",
    "admin": "admin",
}


# Set default value
def get_init_balance(username):
    match username:
        case "sinistre":
            return 1500

        case "prof":
            return 700

        case "admin":
            return 10_000


def is_valid_name(name):
    if name in list(USER_PWD.keys()):
        return True
    return False


def do_transfer(from_name, to, amount):
    amount = int(amount)
    print(f"begin do_transfer({from_name}, {to}, {amount})")

    qry = User.name == from_name
    if True:
        res = db.search(qry)
        balance = res[0]["balance"]
        balance = balance - amount

        history = res[0]["history"]
        history.append({"from": from_name, "to": to, "amount": amount})

        output = {"balance": balance, "history": history}
        db.update(output, qry)

    qry = User.name == to
    if True:
        res = db.search(qry)
        balance = res[0]["balance"]
        balance = balance + amount

        history = res[0]["history"]
        history.append({"from": from_name, "to": to, "amount": amount})

        output = {"balance": balance, "history": history}
        db.update(output, qry)

    qry = User.name == "__history__"
    if True:
        res = db.search(qry)
        history = res[0]["history"]
        history.append({"from": from_name, "to": to, "amount": amount})
        db.update({"history": history}, qry)
        print(history)

    print("=== end do_transfer ===\n")


def init():
    BasicAuth(
        app,
        USER_PWD,
        secret_key="cyber_elephant",
        # groups not in use
        user_groups={"player": ["sinistre", "prof"], "pnj": ["admin"]},
    )
    db.insert({"name": "__history__", "balance": 0, "history": []})
    for user in USER_PWD.keys():
        amount = get_init_balance(user)
        db.insert({"name": user, "balance": amount, "history": []})

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
                            placeholder="send to",
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
            dbc.Col(
                [dbc.Button("Transfer", color="success", id="do-transfer", href="/")]
            ),
        ]
    )

    # Special case for admin
    layout = [
        html.H2("placeholder name", id="name"),
        html.Hr(),
        ret,
        html.Hr(),
        html.H2("History"),
        html.Div(id="history_table"),
    ]

    app.layout = html.Div(
        [
            html.Div(id="output", children=layout),
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="history", storage_type="local", data=[]),
        ],
        className="container",
    )

    @app.callback(
        [
            Output(component_id="name", component_property="children"),
            Output(component_id="balance", component_property="children"),
            Output(component_id="history_table", component_property="children"),
        ],
        [
            Input(component_id="url", component_property="pathname"),
            Input(component_id="do-transfer", component_property="n_clicks"),
        ],
        [
            State(component_id="transfer-id", component_property="value"),
            State(component_id="transfer-amount", component_property="value"),
        ],
        allow_duplicate=True,
    )
    def update_output_div(pathname, n_clicks, transfer_id, transfer_amount):
        username = request.authorization["username"]
        print(ctx)

        last_trig = ctx.triggered_id
        match last_trig:
            case "url":
                print("initial load")

            case "do-transfer":
                print(f"perform transfer({transfer_id}, {transfer_amount})")
                if is_valid_name(transfer_id) and isinstance(transfer_amount, int):
                    do_transfer(username, transfer_id, transfer_amount)

        history_table, curr_balance = make_history_table(username)

        return [username, curr_balance, history_table]


def make_history_table(username):
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
    init_val = get_init_balance(username)
    val = init_val
    history = db.search(User.name == username)[0]["history"]
    for row in history:
        print(">> ", row)
        if row["from"] == "bank":
            continue

        if username == row["from"]:
            amount = float(row["amount"])
            val = val - amount
            curr_val = val
            curr_row = list(row.values())
            curr_row.append(curr_val)
            transactions.append(curr_row)
        elif username == row["to"]:
            amount = float(row["amount"])
            val = val + amount
            curr_val = val
            curr_row = list(row.values())
            curr_row.append(curr_val)
            transactions.append(curr_row)

    def make_line(t):
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


def main():
    # db.truncate()
    init()
    # do_transfer("admin", "sinistre", 150)
    # do_transfer("prof", "sinistre", 300)
    # do_transfer("sinistre", "prof", 150)
    print(db.all())
    app.run_server(host="192.168.1.130", port=36050, debug=True)


if __name__ == "__main__":
    main()
