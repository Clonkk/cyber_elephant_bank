import dash
from dash import html, dcc, Input, Output
from dash_auth import protected_callback, check_groups

dash.register_page(__name__)


def layout(**_kwargs):
    # A check to make sure a player isn't trying to access the admin panel
    if check_groups(["admin"]):
        # TODO Make admin panel layout
        layout = html.Div(
            [
                html.H1("This is our Analytics page"),
                html.Div(
                    [
                        "Select a city: ",
                        dcc.RadioItems(
                            options=["New York City", "Montreal", "San Francisco"],
                            value="Montreal",
                            id="analytics-input",
                        ),
                    ]
                ),
                html.Br(),
                html.Div(id="analytics-output"),
            ]
        )

        # TODO Make admin panel callback
        @protected_callback(
            Output("analytics-output", "children"),
            Input("analytics-input", "value"),
            groups=["admin"],
        )
        def update_city_selected(input_value):
            return f"You selected: {input_value}"

        return layout

    else:
        layout = []
