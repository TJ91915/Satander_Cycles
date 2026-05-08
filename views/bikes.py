"""Bikes tab — top 10 IDs, KPI highlights, stacked rentals over time, summary table."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import C_EBIKE, C_RIDES, style

FREQ_MAP = {"Day": "D", "Month": "MS", "Year": "YS"}
PERIOD_LABEL = {"Day": "Daily", "Month": "Monthly", "Year": "Yearly"}


def _bike_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per bike — rides, time, span, model. Used for KPIs + table."""
    return (
        df[df["bike_id"] != ""].groupby("bike_id")
          .agg(
              rides=("bike_id", "size"),
              first_ridden=("start_dt", "min"),
              last_ridden=("start_dt", "max"),
              total_min=("duration_min", "sum"),
              model=("bike_model", lambda s: s.mode().iat[0] if not s.mode().empty else ""),
          )
          .reset_index()
    )


def render(df: pd.DataFrame) -> None:
    summary = _bike_summary(df)

    # ---------- KPI row: standout bikes ----------
    if not summary.empty:
        most_rides = summary.loc[summary["rides"].idxmax()]
        most_time  = summary.loc[summary["total_min"].idxmax()]
        spans = summary.assign(
            span_days=(summary["last_ridden"] - summary["first_ridden"]).dt.days,
        )
        longest_span = spans.loc[spans["span_days"].idxmax()]

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Most rides",
            most_rides["bike_id"],
            f"{int(most_rides['rides'])} rides",
            delta_color="off",
        )
        c2.metric(
            "Most time on bike",
            most_time["bike_id"],
            f"{most_time['total_min']/60:.1f} hrs",
            delta_color="off",
        )
        c3.metric(
            "Longest span between first & last ride",
            longest_span["bike_id"],
            f"{int(longest_span['span_days'])} days "
            f"({longest_span['first_ridden']:%b %Y} → {longest_span['last_ridden']:%b %Y})",
            delta_color="off",
        )
        st.divider()

    # ---------- Top 10 + stacked rentals ----------
    left, right = st.columns([1, 1.3])

    with left:
        st.subheader("Top 10 most-ridden bikes")
        top_bikes = (
            df["bike_id"].replace("", pd.NA).dropna()
              .value_counts().head(10).iloc[::-1]
        )
        # Force categorical y so each bike ID is its own row, not a numeric scale.
        labels = top_bikes.index.astype(str).tolist()
        fig = go.Figure(go.Bar(
            x=top_bikes.values,
            y=labels,
            orientation="h",
            marker_color=C_RIDES,
            text=top_bikes.values,
            textposition="outside",
            cliponaxis=False,
        ))
        fig.update_layout(
            height=460,
            xaxis_title="Rides",
            yaxis_title="Bike ID",
            margin=dict(l=10, r=40, t=30, b=10),
            yaxis=dict(type="category", automargin=True),
            xaxis=dict(automargin=True),
        )
        st.plotly_chart(style(fig), use_container_width=True)

    with right:
        st.subheader("Rentals over time")
        period = st.selectbox(
            "Aggregation",
            list(FREQ_MAP.keys()),
            index=1,  # default to Month
            key="bikes_rentals_freq",
            label_visibility="collapsed",
        )
        freq = FREQ_MAP[period]

        agg = (
            df.set_index("start_dt")
              .groupby([pd.Grouper(freq=freq), "is_ebike"]).size()
              .unstack(fill_value=0)
              .reindex(columns=[False, True], fill_value=0)
              .rename(columns={False: "Classic", True: "Ebike"})
        )

        fig2 = go.Figure()
        fig2.add_bar(
            x=agg.index, y=agg["Classic"],
            name="Classic", marker_color=C_RIDES,
        )
        fig2.add_bar(
            x=agg.index, y=agg["Ebike"],
            name="Ebike", marker_color=C_EBIKE,
        )
        fig2.update_layout(
            barmode="stack",
            height=420,
            xaxis_title=None,
            yaxis_title=f"{PERIOD_LABEL[period]} rides",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=30, b=10),
        )
        if period == "Year":
            fig2.update_xaxes(tickmode="linear", dtick="M12", tickformat="%Y")
        st.plotly_chart(style(fig2), use_container_width=True)

    st.divider()

    # ---------- Bike summary table ----------
    st.subheader("All bikes — usage summary")
    table = summary.sort_values("rides", ascending=False).copy()
    table["First ridden"] = table["first_ridden"].dt.strftime("%d %b %Y")
    table["Last ridden"]  = table["last_ridden"].dt.strftime("%d %b %Y")
    table["Hours"] = (table["total_min"] / 60).round(1)
    table["Span (days)"] = (table["last_ridden"] - table["first_ridden"]).dt.days

    table = table[[
        "bike_id", "model", "rides",
        "First ridden", "Last ridden", "Span (days)", "Hours",
    ]].rename(columns={
        "bike_id": "Bike ID",
        "model":   "Model",
        "rides":   "Rides",
    })

    st.dataframe(table, use_container_width=True, height=400)
