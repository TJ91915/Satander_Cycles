"""Tariff-era pricing model and per-rental cost attribution.

Two views per rental:
1. Modelled — what the user would have paid using Day Passes (where available),
   per-ride for Era 2, with rolling 24h pass windows.
2. Actual — real charges from rental log Final price + Payments
   (Bike Rental day-access, Late Return Charge, amortised Membership Subscription).

Notes on data semantics:
- Final price on the rental log represents per-ride overcharges (e-bike supplement
  £1, Era 1 overage £2, attempted late-return billing £300). Base ride costs live
  in Payments. So actual_total = rental log Final price + Payments-side charges.
- Membership Additional Charges in Payments are excluded from actual cost: they
  duplicate the £1 e-bike supplements already on rental log Final price.
- Bike 20548's £300 rental-log Final price is a billing attempt, not money paid.
  We zero it out for non-return rentals and use Payments Late Return Charges
  (with refunds netted) as the truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import ceil

import pandas as pd

# ---------- Tariff config ----------

@dataclass(frozen=True)
class TariffEra:
    name: str
    start: date          # inclusive
    end: date | None     # inclusive; None = current
    has_day_pass: bool
    # Day Pass (used when has_day_pass=True; classic bike rates)
    day_pass_price: float
    day_pass_allowance_min: int
    day_pass_overage_block_min: int
    day_pass_overage_rate: float
    # E-bike on Day Pass (Eras 3, 4 only — zeroed in Era 1 since e-bikes didn't exist)
    day_pass_ebike_supplement: float
    day_pass_ebike_overage_rate: float
    # Per-ride pricing (used when has_day_pass=False, i.e. Era 2)
    classic_per_30m: float
    ebike_per_30m: float
    # Membership reference (for amortisation context only)
    annual_fee: float
    monthly_fee: float | None


ERAS: tuple[TariffEra, ...] = (
    TariffEra(
        name="Era 1: Legacy day-access",
        start=date(2010, 7, 30),
        end=date(2022, 9, 11),
        has_day_pass=True,
        day_pass_price=2.00,
        day_pass_allowance_min=30,
        day_pass_overage_block_min=30,
        day_pass_overage_rate=2.00,
        day_pass_ebike_supplement=0.0,
        day_pass_ebike_overage_rate=0.0,
        classic_per_30m=0.0,
        ebike_per_30m=0.0,
        annual_fee=90.00,
        monthly_fee=None,
    ),
    TariffEra(
        name="Era 2: Per-ride only",
        start=date(2022, 9, 12),
        end=date(2024, 3, 2),
        has_day_pass=False,
        day_pass_price=0.0,
        day_pass_allowance_min=0,
        day_pass_overage_block_min=30,
        day_pass_overage_rate=0.0,
        day_pass_ebike_supplement=0.0,
        day_pass_ebike_overage_rate=0.0,
        classic_per_30m=1.65,
        ebike_per_30m=3.30,
        annual_fee=120.00,
        monthly_fee=20.00,
    ),
    TariffEra(
        name="Era 3: Day Pass returns",
        start=date(2024, 3, 3),
        end=date(2025, 4, 5),
        has_day_pass=True,
        day_pass_price=3.00,
        day_pass_allowance_min=30,
        day_pass_overage_block_min=30,
        day_pass_overage_rate=1.65,
        day_pass_ebike_supplement=1.00,
        day_pass_ebike_overage_rate=3.00,
        classic_per_30m=1.65,
        ebike_per_30m=3.30,
        annual_fee=120.00,
        monthly_fee=20.00,
    ),
    TariffEra(
        name="Era 4: Current",
        start=date(2025, 4, 6),
        end=None,
        has_day_pass=True,
        day_pass_price=3.50,
        day_pass_allowance_min=60,
        day_pass_overage_block_min=60,
        day_pass_overage_rate=1.65,
        day_pass_ebike_supplement=1.00,
        day_pass_ebike_overage_rate=3.00,
        classic_per_30m=1.65,
        ebike_per_30m=3.00,
        annual_fee=120.00,
        monthly_fee=20.00,
    ),
)


def tariff_for(ts) -> TariffEra:
    """Return the tariff era active at the given timestamp (datetime/date/Timestamp)."""
    d = ts.date() if hasattr(ts, "date") and callable(ts.date) else ts
    for era in ERAS:
        if era.start <= d and (era.end is None or d <= era.end):
            return era
    raise ValueError(f"No tariff era covers {ts!r}")


# ---------- Constants ----------

NON_RETURN_THRESHOLD_MIN = 24 * 60  # >24h = non-return, late return charge applies


# ---------- Payments → rental attribution ----------

def attribute_bike_rental_fees(
    rentals: pd.DataFrame, payments: pd.DataFrame,
) -> dict[int, float]:
    """Era 1 day-access £2 from Payments, attributed to the rental that triggered it.

    Match: each Bike Rental Payment row to the rental with the closest start_dt
    on the same calendar day. Returns {rental_idx: signed_amount}.
    """
    bike_rentals = payments[payments["context"] == "Bike Rental"]
    if bike_rentals.empty:
        return {}

    attribution: dict[int, float] = {}
    for _, p in bike_rentals.iterrows():
        same_day = rentals[rentals["start_dt"].dt.date == p.payment_dt.date()]
        if same_day.empty:
            continue
        idx = (same_day["start_dt"] - p.payment_dt).abs().idxmin()
        attribution[idx] = attribution.get(idx, 0.0) + float(p.signed_amount)
    return attribution


def attribute_late_returns(
    rentals: pd.DataFrame, payments: pd.DataFrame,
) -> dict[int, float]:
    """Late Return Charges from Payments, attributed to the non-return rental.

    For each rental with duration > 24h, sum signed Late Return Charges whose
    payment date falls between the rental's start_dt and end_dt + 90 days
    (the buffer covers delayed billing and refunds posted weeks later).
    """
    late_charges = payments[payments["context"] == "Late Return Charge"]
    if late_charges.empty:
        return {}

    attribution: dict[int, float] = {}
    for i, r in enumerate(rentals.itertuples(index=False)):
        duration = r.duration_min if pd.notna(r.duration_min) else 0
        if duration <= NON_RETURN_THRESHOLD_MIN:
            continue
        window_end = (r.end_dt + pd.Timedelta(days=90)) if pd.notna(r.end_dt) \
                     else (r.start_dt + pd.Timedelta(days=180))
        mask = (late_charges["payment_dt"] >= r.start_dt) & \
               (late_charges["payment_dt"] <= window_end)
        attribution[i] = float(late_charges.loc[mask, "signed_amount"].sum())
    return attribution


def attribute_membership(
    rentals: pd.DataFrame, payments: pd.DataFrame,
) -> dict[int, dict]:
    """Annual fees from Payments, amortised both per-day (fee/365) and per-ride
    (fee / N rides in the subscription year). Subscription year = exact 1 calendar
    year from each accepted Membership Subscription timestamp.

    Returns {rental_idx: {per_day, per_ride, period_id, period_start, period_end,
    period_amount}}. Rentals outside any subscription window get no entry.
    """
    subs = payments[payments["context"] == "Membership Subscription"] \
        .sort_values("payment_dt").reset_index(drop=True)
    if subs.empty:
        return {}

    attribution: dict[int, dict] = {}
    for j, sub in subs.iterrows():
        period_start = sub.payment_dt
        period_end = period_start + pd.DateOffset(years=1)
        period_amount = float(sub.signed_amount)

        in_period_mask = (rentals["start_dt"] >= period_start) & \
                         (rentals["start_dt"] < period_end)
        in_period_idx = rentals.loc[in_period_mask].index.tolist()
        n_rides = len(in_period_idx)
        if n_rides == 0:
            continue

        per_day = period_amount / 365.0
        per_ride = period_amount / n_rides

        for i in in_period_idx:
            attribution[i] = {
                "per_day": per_day,
                "per_ride": per_ride,
                "period_id": j,
                "period_start": period_start,
                "period_end": period_end,
                "period_amount": period_amount,
            }
    return attribution


# ---------- Modelled cost (Day Pass everywhere available) ----------

def compute_modelled_cost(
    rentals: pd.DataFrame, late_attr: dict[int, float],
) -> pd.DataFrame:
    """Walk rentals chronologically, apply rolling 24h Day Pass logic.

    Algorithm:
    - Sort by start_dt.
    - For each ride, determine era from start time.
    - On era change, reset pass tracker (a pass doesn't carry across eras).
    - If era has Day Pass: buy a new pass when active pass has expired (or none);
      otherwise the ride is free under the current pass (overage still applies).
    - For Era 2 (no Day Pass): per-ride pricing scaled by 30-min blocks.
    - Non-return rentals (>24h): skip computed overage; use the actual matched
      Late Return Charge from Payments.
    """
    n = len(rentals)
    pass_cost  = [0.0] * n
    overage    = [0.0] * n
    ebike_supp = [0.0] * n
    late_ret   = [0.0] * n
    pass_window_start: list[pd.Timestamp | None] = [None] * n
    era_names  = [""] * n
    non_return = [False] * n
    reasons    = [""] * n

    pass_expires_at: pd.Timestamp | None = None
    pass_started_at: pd.Timestamp | None = None
    prev_era_name: str | None = None

    for i, r in enumerate(rentals.itertuples(index=False)):
        era = tariff_for(r.start_dt)
        era_names[i] = era.name
        is_ebike = (r.bike_model == "PBSC_EBIKE")
        duration = float(r.duration_min) if pd.notna(r.duration_min) else 0.0
        is_non_return = duration > NON_RETURN_THRESHOLD_MIN
        non_return[i] = is_non_return
        late_ret[i] = late_attr.get(i, 0.0)

        # Reset pass tracker on era change
        if era.name != prev_era_name:
            pass_expires_at = None
            pass_started_at = None
        prev_era_name = era.name

        if era.has_day_pass:
            # New pass needed?
            if pass_expires_at is None or r.start_dt > pass_expires_at:
                pass_expires_at = r.start_dt + timedelta(hours=24)
                pass_started_at = r.start_dt
                pass_cost[i] = era.day_pass_price
                pass_reason = f"Day Pass £{era.day_pass_price:.2f} (new 24h window)"
            else:
                pass_cost[i] = 0.0
                pass_reason = f"Covered by Day Pass from {pass_started_at:%d/%m %H:%M}"

            pass_window_start[i] = pass_started_at

            # Overage: skipped for non-returns (use actual late return charge)
            if is_non_return:
                overage[i] = 0.0
                ovg_reason = ""
            else:
                allowance = era.day_pass_allowance_min
                block = era.day_pass_overage_block_min
                if duration > allowance:
                    over_min = duration - allowance
                    blocks = ceil(over_min / block)
                    rate = era.day_pass_ebike_overage_rate \
                           if is_ebike and era.day_pass_ebike_overage_rate \
                           else era.day_pass_overage_rate
                    overage[i] = blocks * rate
                    ovg_reason = f"+£{overage[i]:.2f} overage ({over_min:.0f}min over {allowance})"
                else:
                    overage[i] = 0.0
                    ovg_reason = ""

            # E-bike supplement on Day Pass (Eras 3, 4 only)
            if is_ebike and era.day_pass_ebike_supplement > 0:
                ebike_supp[i] = era.day_pass_ebike_supplement
                supp_reason = f"+£{ebike_supp[i]:.2f} e-bike"
            else:
                ebike_supp[i] = 0.0
                supp_reason = ""

            parts = [pass_reason, ovg_reason, supp_reason]
            if is_non_return and late_ret[i] != 0:
                parts.append(f"+£{late_ret[i]:.2f} late return")
            reasons[i] = " · ".join(p for p in parts if p)

        else:
            # Era 2: per-ride pricing, no Day Pass
            rate = era.ebike_per_30m if is_ebike else era.classic_per_30m
            blocks = ceil(duration / 30) if duration > 0 else 1
            pass_cost[i] = blocks * rate
            overage[i] = 0.0
            ebike_supp[i] = 0.0
            pass_window_start[i] = None
            pass_expires_at = None
            pass_started_at = None
            kind = "e-bike" if is_ebike else "classic"
            reasons[i] = f"Per-ride £{pass_cost[i]:.2f} (Era 2, {kind}, {blocks}×30min)"
            if is_non_return and late_ret[i] != 0:
                reasons[i] += f" · +£{late_ret[i]:.2f} late return"

    return pd.DataFrame({
        "tariff_era":            era_names,
        "modelled_pass_cost":    pass_cost,
        "modelled_overage":      overage,
        "modelled_ebike_supp":   ebike_supp,
        "modelled_late_return":  late_ret,
        "modelled_total":        [a + b + c + d for a, b, c, d in
                                  zip(pass_cost, overage, ebike_supp, late_ret)],
        "pass_window_start":     pass_window_start,
        "non_return_flag":       non_return,
        "charge_reason":         reasons,
    })


# ---------- Actual cost (rental log + Payments) ----------

def compute_actual_cost(
    rentals: pd.DataFrame,
    bike_rental_attr: dict[int, float],
    late_attr: dict[int, float],
    membership_attr: dict[int, dict],
) -> pd.DataFrame:
    """Per-rental actual money paid.

    Components:
    - actual_final_price_on_log: rental log Final price (zeroed for non-returns
      to avoid double-count with Late Return Charges from Payments)
    - actual_bike_rental_fee:   Era 1 day-access £2 from Payments
    - actual_late_return:       Late Return Charges from Payments (refunds netted)
    - actual_membership_per_day_share / actual_membership_per_ride_share:
      annual fee amortised two ways. View toggles between them.

    Two totals are returned, one per amortisation choice.
    """
    n = len(rentals)
    final_price_on_log = [0.0] * n
    bike_rental_fee    = [0.0] * n
    late_ret           = [0.0] * n
    member_per_day     = [0.0] * n
    member_per_ride    = [0.0] * n
    period_amount      = [0.0] * n
    period_id          = [-1] * n

    for i, r in enumerate(rentals.itertuples(index=False)):
        duration = float(r.duration_min) if pd.notna(r.duration_min) else 0.0
        is_non_return = duration > NON_RETURN_THRESHOLD_MIN

        if is_non_return:
            final_price_on_log[i] = 0.0
        else:
            final_price_on_log[i] = float(r.price_gbp) if pd.notna(r.price_gbp) else 0.0

        bike_rental_fee[i] = bike_rental_attr.get(i, 0.0)
        late_ret[i] = late_attr.get(i, 0.0)

        m = membership_attr.get(i)
        if m is not None:
            member_per_day[i] = m["per_day"]
            member_per_ride[i] = m["per_ride"]
            period_amount[i] = m["period_amount"]
            period_id[i] = m["period_id"]

    total_per_day  = [a + b + c + d for a, b, c, d in
                      zip(final_price_on_log, bike_rental_fee, late_ret, member_per_day)]
    total_per_ride = [a + b + c + d for a, b, c, d in
                      zip(final_price_on_log, bike_rental_fee, late_ret, member_per_ride)]

    return pd.DataFrame({
        "actual_final_price_on_log":         final_price_on_log,
        "actual_bike_rental_fee":            bike_rental_fee,
        "actual_late_return":                late_ret,
        "actual_membership_per_day_share":   member_per_day,
        "actual_membership_per_ride_share":  member_per_ride,
        "actual_total_amort_per_day":        total_per_day,
        "actual_total_amort_per_ride":       total_per_ride,
        "subscription_period_id":            period_id,
        "subscription_period_amount":        period_amount,
    })


# ---------- Top-level orchestrator ----------

def build_cost_dataset(
    rentals: pd.DataFrame, payments: pd.DataFrame,
) -> pd.DataFrame:
    """Single entry point: rentals frame + all modelled and actual cost columns.

    Side effects:
    - Drops Status='Cannot bill' rows (8 rentals with NaN end_dt — billing failed)
    - Sorts chronologically and resets index
    - Adds difference columns (actual − modelled) for both amortisation modes
    """
    rentals = rentals[rentals["status"] != "Cannot bill"].copy()
    rentals = rentals.sort_values("start_dt").reset_index(drop=True)

    bike_rental_attr = attribute_bike_rental_fees(rentals, payments)
    late_attr        = attribute_late_returns(rentals, payments)
    membership_attr  = attribute_membership(rentals, payments)

    modelled = compute_modelled_cost(rentals, late_attr)
    actual   = compute_actual_cost(rentals, bike_rental_attr, late_attr, membership_attr)

    result = pd.concat(
        [rentals.reset_index(drop=True),
         modelled.reset_index(drop=True),
         actual.reset_index(drop=True)],
        axis=1,
    )

    result["cost_difference_per_ride"] = \
        result["actual_total_amort_per_ride"] - result["modelled_total"]
    result["cost_difference_per_day"]  = \
        result["actual_total_amort_per_day"] - result["modelled_total"]

    return result
