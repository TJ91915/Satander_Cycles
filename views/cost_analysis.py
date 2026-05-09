"""Cost Analysis tab — modelled (Day Pass everywhere available) vs actual paid.

Per-rental drill-down is the centerpiece. Aggregates and charts sit above
it for context; subscription-year and non-return summaries below.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cost import ERAS, build_cost_dataset
from lib import (
    C_EBIKE,
    C_NEUTRAL,
    C_RIDES,
    CACHE_TTL,
    load_payments,
    load_rentals,
    style,
)


@st.cache_data(ttl=CACHE_TTL, show_spinner="Building cost dataset…")
def _cost_dataset() -> pd.DataFrame:
    """Load rentals (with bike 20548 included) + payments → enrich with cost columns."""
    rentals = load_rentals(include_excluded=True)
    payments = load_payments()
    return build_cost_dataset(rentals, payments)


def render() -> None:
    df = _cost_dataset()

    st.subheader("Cost analysis")
    st.caption(
        "Modelled cost assumes Day Pass everywhere it existed (Eras 1, 3, 4) and "
        "per-ride pricing in Era 2, with rolling 24h pass windows. Actual cost = "
        "rental log Final price + Bike Rental day-access fees + Late Return Charges "
        "+ amortised Membership Subscription, all from Payments (Accepted only, "
        "refunds netted)."
    )

    # ---------- Amortisation toggle ----------
    amort = st.radio(
        "Membership fee amortisation",
        options=["Per ride", "Per day"],
        horizontal=True,
        help="Per-ride spreads the annual fee across rentals in that subscription year. "
             "Per-day spreads it across 365 days. Both views over the same actual money paid.",
    )
    actual_total_col = (
        "actual_total_amort_per_ride" if amort == "Per ride"
        else "actual_total_amort_per_day"
    )
    member_share_col = (
        "actual_membership_per_ride_share" if amort == "Per ride"
        else "actual_membership_per_day_share"
    )
    diff_col = (
        "cost_difference_per_ride" if amort == "Per ride"
        else "cost_difference_per_day"
    )

    # ---------- KPI cards ----------
    modelled_total = df["modelled_total"].sum()
    actual_total = df[actual_total_col].sum()
    delta = actual_total - modelled_total
    saved = modelled_total - actual_total  # positive = membership saved you money

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Modelled (Day Pass)", f"£{modelled_total:,.2f}")
    c2.metric("Actual paid", f"£{actual_total:,.2f}")
    c3.metric(
        "Saved by being a member",
        f"£{saved:,.2f}" if saved >= 0 else f"−£{-saved:,.2f}",
        delta=f"−£{abs(delta):,.2f}" if delta < 0 else f"+£{delta:,.2f}",
        delta_color="inverse",  # paying less = good (green)
    )
    c4.metric("Total rentals", f"{len(df):,}")

    st.divider()

    # ---------- Filters ----------
    f1, f2, f3, f4 = st.columns([1, 2, 1.2, 1.2])
    years = sorted(df["year"].dropna().unique().tolist())
    sel_years = f1.multiselect("Year", years, default=years)
    eras = [e.name for e in ERAS]
    sel_eras = f2.multiselect("Era", eras, default=eras)
    sel_models = f3.multiselect(
        "Bike model",
        sorted(df["bike_model"].dropna().unique().tolist()),
        default=sorted(df["bike_model"].dropna().unique().tolist()),
    )
    show_only_non_returns = f4.toggle("Non-returns only", value=False)

    mask = (
        df["year"].isin(sel_years)
        & df["tariff_era"].isin(sel_eras)
        & df["bike_model"].isin(sel_models)
    )
    if show_only_non_returns:
        mask &= df["non_return_flag"]
    fdf = df[mask].copy()

    if fdf.empty:
        st.warning("No rentals match the current filters.")
        return

    # ---------- Monthly modelled vs actual ----------
    fdf["year_month"] = fdf["start_dt"].dt.to_period("M").dt.to_timestamp()
    monthly = fdf.groupby("year_month").agg(
        modelled=("modelled_total", "sum"),
        actual=(actual_total_col, "sum"),
    ).reset_index()

    fig_monthly = go.Figure()
    fig_monthly.add_scatter(
        x=monthly["year_month"], y=monthly["modelled"],
        mode="lines+markers", name="Modelled",
        line=dict(color=C_EBIKE, width=2),
    )
    fig_monthly.add_scatter(
        x=monthly["year_month"], y=monthly["actual"],
        mode="lines+markers", name="Actual",
        line=dict(color=C_RIDES, width=2),
    )
    fig_monthly.update_layout(
        title="Monthly cost — modelled vs actual",
        xaxis_title=None, yaxis_title="£ per month",
        height=360,
    )
    fig_monthly.update_yaxes(tickprefix="£", tickformat=",.0f")
    st.plotly_chart(style(fig_monthly), use_container_width=True)

    # ---------- Per-rental drill-down ----------
    st.markdown("##### Per-rental breakdown")

    table_cols = {
        "start_dt":                  "Start",
        "duration_min":              "Mins",
        "bike_model":                "Model",
        "tariff_era":                "Era",
        "modelled_pass_cost":        "M: Pass",
        "modelled_overage":          "M: Overage",
        "modelled_ebike_supp":       "M: E-bike",
        "modelled_late_return":      "M: Late",
        "modelled_total":            "Modelled £",
        "actual_final_price_on_log": "A: Log",
        "actual_bike_rental_fee":    "A: Day-access",
        "actual_late_return":        "A: Late",
        member_share_col:            "A: Member",
        actual_total_col:            "Actual £",
        diff_col:                    "Δ (A − M)",
        "non_return_flag":           "Non-return",
        "charge_reason":             "Modelled reason",
    }
    show = fdf[list(table_cols.keys())].rename(columns=table_cols).copy()
    show["Mins"] = show["Mins"].round(0).astype("Int64")
    show["Start"] = show["Start"].dt.strftime("%Y-%m-%d %H:%M")

    st.dataframe(
        show,
        use_container_width=True,
        height=520,
        hide_index=True,
        column_config={
            "M: Pass":       st.column_config.NumberColumn(format="£%.2f"),
            "M: Overage":    st.column_config.NumberColumn(format="£%.2f"),
            "M: E-bike":     st.column_config.NumberColumn(format="£%.2f"),
            "M: Late":       st.column_config.NumberColumn(format="£%.2f"),
            "Modelled £":    st.column_config.NumberColumn(format="£%.2f"),
            "A: Log":        st.column_config.NumberColumn(format="£%.2f"),
            "A: Day-access": st.column_config.NumberColumn(format="£%.2f"),
            "A: Late":       st.column_config.NumberColumn(format="£%.2f"),
            "A: Member":     st.column_config.NumberColumn(format="£%.3f"),
            "Actual £":      st.column_config.NumberColumn(format="£%.2f"),
            "Δ (A − M)":     st.column_config.NumberColumn(format="£%.2f"),
        },
    )
    st.caption(
        f"{len(show):,} rentals shown. M: = modelled (Day Pass), A: = actual. "
        "Hover the Modelled reason cell to see the full text."
    )

    st.divider()

    # ---------- Subscription year breakdown ----------
    st.markdown("##### Was membership worth it?")

    sub_rows = df[df["subscription_period_id"] >= 0].copy()
    if not sub_rows.empty:
        # Compute per-period totals; period_amount is identical within a period,
        # so we take min/max to get the constant.
        sub_summary = sub_rows.groupby("subscription_period_id").agg(
            rides=("start_dt", "size"),
            modelled=("modelled_total", "sum"),
            actual_excl_member=("actual_final_price_on_log",
                                lambda s: s.sum()
                                          + sub_rows.loc[s.index, "actual_bike_rental_fee"].sum()
                                          + sub_rows.loc[s.index, "actual_late_return"].sum()),
            membership_paid=("subscription_period_amount", "min"),
            period_start=("start_dt", "min"),
            period_end=("start_dt", "max"),
        )
        sub_summary["actual_total"] = (
            sub_summary["actual_excl_member"] + sub_summary["membership_paid"]
        )
        sub_summary["saved_vs_modelled"] = (
            sub_summary["modelled"] - sub_summary["actual_total"]
        )
        sub_summary["period"] = (
            sub_summary["period_start"].dt.strftime("%d %b %Y")
            + " → " + sub_summary["period_end"].dt.strftime("%d %b %Y")
        )

        display = sub_summary[[
            "period", "rides", "modelled", "membership_paid",
            "actual_excl_member", "actual_total", "saved_vs_modelled",
        ]].rename(columns={
            "period":             "Subscription period (rides covered)",
            "rides":              "Rides",
            "modelled":           "Modelled if Day Pass",
            "membership_paid":    "Annual fee paid",
            "actual_excl_member": "Other charges",
            "actual_total":       "Actual total",
            "saved_vs_modelled":  "Saved vs modelled",
        })
        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Modelled if Day Pass": st.column_config.NumberColumn(format="£%.2f"),
                "Annual fee paid":      st.column_config.NumberColumn(format="£%.2f"),
                "Other charges":        st.column_config.NumberColumn(format="£%.2f"),
                "Actual total":         st.column_config.NumberColumn(format="£%.2f"),
                "Saved vs modelled":    st.column_config.NumberColumn(format="£%.2f"),
            },
        )
    else:
        st.info("No subscription periods found in Payments.")

    st.divider()

    # ---------- Non-return summary ----------
    st.markdown("##### Non-return rentals (>24h)")
    nr = df[df["non_return_flag"]]
    if nr.empty:
        st.success("No non-return rentals — every bike was returned within 24h.")
    else:
        n1, n2, n3 = st.columns(3)
        n1.metric("Non-return rentals", f"{len(nr):,}")
        n2.metric("Total late-return paid", f"£{nr['actual_late_return'].sum():,.2f}")
        n3.metric("Modelled (incl. late)", f"£{nr['modelled_total'].sum():,.2f}")

        nr_show = nr[[
            "start_dt", "end_dt", "duration_min", "bike_id", "bike_model",
            "modelled_total", "actual_final_price_on_log", "actual_late_return",
            actual_total_col, "charge_reason",
        ]].rename(columns={
            "start_dt":                  "Start",
            "end_dt":                    "End",
            "duration_min":              "Duration (min)",
            "bike_id":                   "Bike",
            "bike_model":                "Model",
            "modelled_total":            "Modelled £",
            "actual_final_price_on_log": "Final price (log)",
            "actual_late_return":        "Late return paid",
            actual_total_col:            "Actual £",
            "charge_reason":             "Reason",
        }).copy()
        nr_show["Start"] = nr_show["Start"].dt.strftime("%Y-%m-%d %H:%M")
        nr_show["End"] = nr_show["End"].dt.strftime("%Y-%m-%d %H:%M")
        nr_show["Duration (min)"] = nr_show["Duration (min)"].round(0).astype("Int64")
        st.dataframe(
            nr_show, use_container_width=True, hide_index=True,
            column_config={
                "Modelled £":        st.column_config.NumberColumn(format="£%.2f"),
                "Final price (log)": st.column_config.NumberColumn(format="£%.2f"),
                "Late return paid":  st.column_config.NumberColumn(format="£%.2f"),
                "Actual £":          st.column_config.NumberColumn(format="£%.2f"),
            },
        )
        st.caption(
            "The £300 on the rental log for non-returns is what TfL *attempted* to "
            "bill, not what was actually paid. The Late return paid column is the "
            "net of accepted Payments (refunds netted)."
        )
