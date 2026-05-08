"""Trends tab — monthly time series + year×month YoY heatmap."""
from __future__ import annotations

import calendar

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import C_HOURS, C_RIDES, HEAT_SCALE, style


def render(df: pd.DataFrame) -> None:
    monthly = (
        df.set_index("start_dt")
          .resample("MS")
          .agg(rides=("bike_id", "size"), hours=("duration_min", lambda s: s.sum() / 60))
          .reset_index()
          .rename(columns={"start_dt": "month_start"})
    )

    # ---------- Monthly rides ----------
    fig_rides = go.Figure()
    fig_rides.add_scatter(
        x=monthly["month_start"], y=monthly["rides"],
        mode="lines", line=dict(color=C_RIDES, width=2.5),
        fill="tozeroy", fillcolor="rgba(123, 155, 126, 0.15)",
        name="Rides",
    )
    fig_rides.update_layout(
        title="Monthly rides",
        xaxis_title=None, yaxis_title="Rides",
        height=320,
    )

    # ---------- Monthly hours ----------
    # A single forgotten-dock-out can balloon one month's hours and squash the
    # rest of the chart. Cap the y-axis at the second-highest month so the
    # outlier is visible (it pokes above the cap) without flattening the trend.
    sorted_hours = monthly["hours"].sort_values(ascending=False).reset_index(drop=True)
    if len(sorted_hours) >= 2:
        y_cap = sorted_hours.iloc[1] * 1.1
    else:
        y_cap = sorted_hours.iloc[0] * 1.1 if len(sorted_hours) else 1.0

    fig_hours = go.Figure()
    fig_hours.add_scatter(
        x=monthly["month_start"], y=monthly["hours"],
        mode="lines", line=dict(color=C_HOURS, width=2.5),
        fill="tozeroy", fillcolor="rgba(126, 107, 143, 0.15)",
        name="Hours",
    )
    fig_hours.update_layout(
        title="Monthly time on bike",
        xaxis_title=None, yaxis_title="Hours",
        height=320,
        yaxis=dict(range=[0, y_cap]),
    )

    st.plotly_chart(style(fig_rides), use_container_width=True)
    st.plotly_chart(style(fig_hours), use_container_width=True)

    # ---------- Year × month heatmap ----------
    pivot = (
        df.groupby(["year", "month"]).size().unstack(fill_value=0)
          .reindex(columns=range(1, 13), fill_value=0)
    )
    fig_heat = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[calendar.month_abbr[m] for m in pivot.columns],
        y=pivot.index.astype(str),
        colorscale=HEAT_SCALE,
        colorbar=dict(title="Rides"),
        hovertemplate="%{y} %{x}: %{z} rides<extra></extra>",
    ))
    fig_heat.update_layout(
        title="Rides by year × month",
        xaxis_title=None, yaxis_title=None,
        height=420,
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(style(fig_heat), use_container_width=True)
