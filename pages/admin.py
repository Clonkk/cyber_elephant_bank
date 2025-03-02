import dash
from dash import html, dcc, Input, Output, State, ALL, MATCH, ctx, callback
from dash_auth import protected_callback, check_groups
from flask import request
import dash_bootstrap_components as dbc
import main

dash.register_page(__name__)


def layout(**_kwargs):
    # A check to make sure a player isn't trying to access the admin panel
    if check_groups(["admin"]):
        table_header = [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Personnage"),
                        html.Th("Solde"),
                        html.Th("Modifier"),
                    ]
                )
            )
        ]

        rows = []
        admin_msgs = []

        for row in main.db:
            if row["name"] in ["bank", "__history__"]:
                continue
            table_row = []
            for key, val in row.items():
                table_row.append(
                    html.Td(val),
                )
            name = row["name"]
            balance = row["balance"]
            rows.append(
                html.Tr(
                    [
                        html.Td(name),
                        html.Td(balance),
                        dbc.Row(
                            [
                                dbc.Col(
                                    dbc.Input(
                                        id={
                                            "type": "admin-transfer-amount",
                                            "index": f"{name}",
                                        },
                                        step=1,
                                        placeholder=0.0,
                                        type="number",
                                    )
                                ),
                                dbc.Col(
                                    dbc.Button(
                                        "Modifier solde",
                                        color="primary",
                                        outline=True,
                                        id={
                                            "type": "admin-do-transfer-amount",
                                            "index": f"{name}",
                                        },
                                    )
                                ),
                            ]
                        ),
                    ]
                )
            )
            admin_msgs.append(
                dbc.Alert(
                    f"This is an alert message for {name}. Scary!",
                    id={
                        "type": "admin-msg",
                        "index": f"{name}",
                    },
                    dismissable=False,
                    is_open=False,
                    color="success",
                ),
            )

        admin_msgs.append(
            dbc.Alert(
                "This is an alert message. Scary!",
                id="admin-msg",
                dismissable=False,
                is_open=False,
                color="success",
            ),
        )

        table_body = [html.Tbody(rows)]
        table = dbc.Table(
            # using the same table as in the above example
            table_header + table_body,
            bordered=True,
            hover=True,
            responsive=True,
            striped=True,
        )

        layout = [
            html.Div(admin_msgs),
            html.Div(table),
        ]
        return layout

    else:
        return []
