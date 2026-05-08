"""Stations tab — top 15 most-used stations + top 20 routes table."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import C_NEUTRAL, C_RIDES, style


def render(df: pd.DataFrame) -> None:
    left, right = st.columns([1, 1])

    with left:
        st.subheader("Top 15 stations")
        station_counts = (
            pd.concat([df["start_station"], df["end_station"]])
              .replace("", pd.NA).dropna()
              .value_counts()
              .head(15)
              .iloc[::-1]   # so the most-used appears at the top of the bar chart
        )
        fig = go.Figure(go.Bar(
            x=station_counts.values,
            y=station_counts.index,
            orientation="h",
            marker_color=C_RIDES,
        ))
        fig.update_layout(
            title=None,
            height=540,
            xaxis_title="Total visits (start + end)",
            yaxis_title=None,
            margin=dict(l=10, r=20, t=20, b=10),
            yaxis=dict(automargin=True),
        )
        st.plotly_chart(style(fig), use_container_width=True)

    with right:
        st.subheader("Top 20 routes")
        routes = (
            df.groupby(["start_station", "end_station"]).size()
              .reset_index(name="rides")
              .sort_values("rides", ascending=False)
              .head(20)
              .reset_index(drop=True)
        )
        routes.index = routes.index + 1
        st.dataframe(
            routes.rename(columns={
                "start_station": "Start",
                "end_station":   "End",
                "rides":         "Rides",
            }),
            use_container_width=True,
            height=520,
        )

    st.divider()

    # Start vs end pattern — simple split
    st.subheader("Start vs end usage")
    start_top = df["start_station"].value_counts().head(10)
    end_top   = df["end_station"].value_counts().head(10)
    fig2 = go.Figure()
    fig2.add_bar(
        name="Started here", x=start_top.index, y=start_top.values,
        marker_color=C_RIDES,
    )
    fig2.add_bar(
        name="Ended here", x=end_top.index, y=end_top.values,
        marker_color=C_NEUTRAL,
    )
    fig2.update_layout(
        barmode="group",
        height=380,
        xaxis_title=None, yaxis_title="Rides",
        xaxis_tickangle=-30,
    )
    st.plotly_chart(style(fig2), use_container_width=True)
