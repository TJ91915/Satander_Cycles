"""Overview tab — headline KPIs, yearly rides with ebike split, bike-model breakdown."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import C_EBIKE, C_NEUTRAL, C_RIDES, style


def render(df: pd.DataFrame) -> None:
    # ---------- KPI row ----------
    total_rides   = len(df)
    total_hours   = df["duration_min"].sum() / 60
    avg_ride_min  = df["duration_min"].mean()
    unique_bikes  = df["bike_id"].nunique()
    ebike_share   = df["is_ebike"].mean() * 100 if total_rides else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total rides", f"{total_rides:,}")
    c2.metric("Total time", f"{total_hours:,.0f} hrs")
    c3.metric("Avg ride", f"{avg_ride_min:.0f} min")
    c4.metric("Unique bikes", f"{unique_bikes:,}")
    c5.metric("Ebike share", f"{ebike_share:.1f}%")

    st.divider()

    # ---------- Yearly rides with classic/ebike split ----------
    yearly = (
        df.groupby(["year", "is_ebike"]).size().unstack(fill_value=0)
        .rename(columns={False: "Classic", True: "Ebike"})
        .reindex(columns=["Classic", "Ebike"], fill_value=0)
    )

    fig_year = go.Figure()
    fig_year.add_bar(
        x=yearly.index, y=yearly["Classic"],
        name="Classic", marker_color=C_RIDES,
    )
    fig_year.add_bar(
        x=yearly.index, y=yearly["Ebike"],
        name="Ebike", marker_color=C_EBIKE,
    )
    fig_year.update_layout(
        barmode="stack",
        title="Rides per year",
        xaxis_title=None, yaxis_title="Rides",
        height=380,
    )
    fig_year.update_xaxes(tickmode="linear", dtick=1)

    # ---------- Bike model doughnut ----------
    model_counts = df["bike_model"].value_counts()
    if model_counts.empty:
        model_counts = pd.Series({"Unknown": total_rides})

    fig_model = go.Figure(go.Pie(
        labels=model_counts.index,
        values=model_counts.values,
        hole=0.55,
        marker=dict(colors=[C_RIDES, C_EBIKE, C_NEUTRAL, "#9C7A5B", "#7E6B8F"]),
        textinfo="label+percent",
    ))
    fig_model.update_layout(title="Bike model split", height=380, showlegend=False)

    left, right = st.columns([1.4, 1])
    with left:
        st.plotly_chart(style(fig_year), use_container_width=True)
    with right:
        st.plotly_chart(style(fig_model), use_container_width=True)
