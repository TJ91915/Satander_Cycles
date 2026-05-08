"""Shared helpers for the Santander Cycles dashboard: auth, palette, chart styling, loaders."""
from __future__ import annotations

import json
import time
from pathlib import Path

import folium
import gspread
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from google.oauth2.service_account import Credentials

CACHE_TTL = 7200  # 2 hours

# ---------- sheets ----------
SHEET_ID_RENTALS  = "1UlnOyrkfry7tpxhxWqWLP3pHmzTOV52qKZhGpcFABVk"
SHEET_ID_DOCKS    = "1eAFmEryZF5xUOxBjkFe2iZRDkWa-Us4zMfGfKSNhMfY"
SHEET_ID_PAYMENTS = "1GgAAjcPmsH_bv_bu2_UH8cV015Rh2mloqh9YoyHyMhk"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
LOCAL_KEY = Path(__file__).parent / "service-account-key.json"
ASSETS = Path(__file__).parent / "assets"
ROAD_MAP_HTML        = ASSETS / "london_road_routes_map.html"
ROUTE_GEOMETRY_CACHE = ASSETS / "route_geometry_cache.json"
ROUTE_FINGERPRINT    = ASSETS / "route_fingerprint.txt"

OSRM_URL = (
    "http://router.project-osrm.org/route/v1/cycling/"
    "{slon},{slat};{elon},{elat}?overview=full&geometries=geojson"
)

# Date format used across all three sheets
DATE_FMT = "%d/%m/%Y %H:%M"

# Bikes excluded from every calculation (KPIs, charts, road map).
# 20548 — stolen mid-rental; never docked back, so its trip duration is days not minutes.
EXCLUDED_BIKE_IDS: frozenset[str] = frozenset({"20548"})

# ---------- palette (cosy farmhouse, mirrors HouseData) ----------
C_RIDES     = "#7B9B7E"   # sage — classic bike, default ride colour
C_EBIKE     = "#C07855"   # warm terracotta — ebike, accent
C_HOURS     = "#7E6B8F"   # dusty plum — time/duration
C_NEUTRAL   = "#D4C5A9"   # soft tan — secondary bars
C_TEXT      = "#2F3640"   # soft charcoal
C_GRID      = "#D8D1C3"   # faint sandstone
C_BG        = "#F7F4EE"   # warm cream

# Heatmap for the YoY year×month grid: cream → sage → warm tan
HEAT_SCALE = [[0, "#F3EADB"], [0.5, "#A8B89F"], [1, "#7B9B7E"]]

CATEGORICAL = [C_RIDES, C_EBIKE, C_HOURS, C_NEUTRAL, "#9C7A5B", "#6B8DA8"]


# ---------- auth ----------
def credentials() -> Credentials:
    """Prefer Streamlit secrets (cloud); fall back to local JSON key."""
    try:
        info = dict(st.secrets["gcp_service_account"])
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        pass
    if LOCAL_KEY.exists():
        return Credentials.from_service_account_file(str(LOCAL_KEY), scopes=SCOPES)
    raise RuntimeError(
        "No credentials. Put service-account-key.json in project root, "
        "or configure [gcp_service_account] in .streamlit/secrets.toml."
    )


def client() -> gspread.Client:
    return gspread.authorize(credentials())


def style(fig: go.Figure) -> go.Figure:
    """Apply the shared farmhouse layout to any Plotly figure."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=C_TEXT, family="sans-serif", size=13),
        title=dict(font=dict(size=15, color=C_TEXT)),
        colorway=CATEGORICAL,
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor=C_GRID, linecolor=C_GRID, zerolinecolor=C_GRID)
    fig.update_yaxes(gridcolor=C_GRID, linecolor=C_GRID, zerolinecolor=C_GRID)
    return fig


def _is_ebike(model: pd.Series) -> pd.Series:
    """Heuristic: any model whose name suggests an electric bike.

    TfL has used several literal names over the years — `PBSC E-Bike`,
    `E-Bike`, `Pedelec`. Match any of them case-insensitively without
    catching plain `Classic Bike`.
    """
    return model.fillna("").str.contains(r"e[-\s]?bike|pedelec|pbsc", case=False, regex=True)


# ---------- loaders ----------
@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading rental data…")
def load_rentals() -> pd.DataFrame:
    """One row per trip with parsed dates, durations, stations, bike + derived columns.

    Source columns (literal headers):
      Rental number, Start date, Member name, Status, Start station,
      Billable duration, Final price, End date, Bike, Bike model, End station,
      Start station lat, Start station long, End station lat, End station long
    """
    ws = client().open_by_key(SHEET_ID_RENTALS).get_worksheet(0)
    rows = ws.get_all_values()
    df = pd.DataFrame(rows[1:], columns=[c.strip() for c in rows[0]])

    df["start_dt"] = pd.to_datetime(df["Start date"], format=DATE_FMT, errors="coerce")
    df["end_dt"]   = pd.to_datetime(df["End date"],   format=DATE_FMT, errors="coerce")

    # Duration: prefer end-start; the "Billable duration" column on TfL exports
    # is sometimes a string like "0:13:00" and sometimes the same minutes count
    # — computing from timestamps is the most reliable.
    df["duration_min"] = (df["end_dt"] - df["start_dt"]).dt.total_seconds() / 60

    # Final price — strip £ and any thousands separator, coerce to float
    df["price_gbp"] = pd.to_numeric(
        df["Final price"].astype(str)
            .str.replace("£", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.strip(),
        errors="coerce",
    )

    df["start_station"] = df["Start station"].str.strip()
    df["end_station"]   = df["End station"].str.strip()
    df["bike_id"]       = df["Bike"].astype(str).str.strip()
    df["bike_model"]    = df["Bike model"].str.strip()
    df["status"]        = df["Status"].str.strip()
    df["member"]        = df["Member name"].str.strip()

    for col, alias in [
        ("Start station lat",  "start_lat"),
        ("Start station long", "start_lng"),
        ("End station lat",    "end_lat"),
        ("End station long",   "end_lng"),
    ]:
        df[alias] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["start_dt"]).copy()

    # Exclude bikes flagged as data anomalies (e.g. stolen mid-rental — see EXCLUDED_BIKE_IDS).
    excluded_mask = df["bike_id"].isin(EXCLUDED_BIKE_IDS)
    excluded_count = int(excluded_mask.sum())
    df = df[~excluded_mask].copy()

    df = df.sort_values("start_dt").reset_index(drop=True)
    df.attrs["excluded_trip_count"] = excluded_count
    df.attrs["excluded_bike_ids"] = sorted(EXCLUDED_BIKE_IDS)

    df["is_ebike"]    = _is_ebike(df["bike_model"])
    df["year"]        = df["start_dt"].dt.year
    df["month"]       = df["start_dt"].dt.month
    df["year_month"]  = df["start_dt"].dt.to_period("M").dt.to_timestamp()
    df["weekday"]     = df["start_dt"].dt.weekday
    df["hour"]        = df["start_dt"].dt.hour
    df["date"]        = df["start_dt"].dt.date

    return df


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading dock locations…")
def load_docks() -> pd.DataFrame:
    """Station catalogue with coordinates and capacity.

    Source columns: ID, Name, Terminal Name, lat, long, number of docs (nbDocks)
    """
    ws = client().open_by_key(SHEET_ID_DOCKS).get_worksheet(0)
    rows = ws.get_all_values()
    df = pd.DataFrame(rows[1:], columns=[c.strip() for c in rows[0]])

    df["dock_id"]       = df["ID"].astype(str).str.strip()
    df["name"]          = df["Name"].str.strip()
    df["terminal_name"] = df["Terminal Name"].str.strip()
    df["lat"]           = pd.to_numeric(df["lat"], errors="coerce")
    df["lng"]           = pd.to_numeric(df["long"], errors="coerce")

    capacity_col = next(
        (c for c in df.columns if c.lower().startswith("number of docs") or c.lower() == "nbdocks"),
        None,
    )
    df["capacity"] = pd.to_numeric(df[capacity_col], errors="coerce") if capacity_col else pd.NA

    return df.dropna(subset=["lat", "lng"]).reset_index(drop=True)[
        ["dock_id", "name", "terminal_name", "lat", "lng", "capacity"]
    ]


@st.cache_data
def load_road_map_html() -> str:
    """Pre-generated Folium map of road-routed journeys. Cached for the session."""
    return ROAD_MAP_HTML.read_text()


def road_map_mtime() -> str:
    """Last-modified date of the road-routes HTML, formatted for display."""
    if not ROAD_MAP_HTML.exists():
        return "—"
    return pd.Timestamp(ROAD_MAP_HTML.stat().st_mtime, unit="s").strftime("%d %b %Y")


# ---------- road map: stale-check + regeneration ----------
def _route_key(slat: float, slon: float, elat: float, elon: float) -> str:
    """Stable string key for a unique start-end coordinate pair (5 dp ≈ 1m)."""
    return f"{slat:.5f},{slon:.5f},{elat:.5f},{elon:.5f}"


def _unique_routes(df: pd.DataFrame) -> pd.DataFrame:
    """Frequency table of unique start→end coordinate pairs from the rental log."""
    coords = ["start_lat", "start_lng", "end_lat", "end_lng"]
    clean = df.dropna(subset=coords)
    return (
        clean.groupby(coords).size()
             .reset_index(name="count")
             .sort_values("count", ascending=False)
             .reset_index(drop=True)
    )


def _fingerprint(routes: pd.DataFrame) -> str:
    """Stable hash of the unique-routes set so we can detect 'new data since last regen'."""
    return "\n".join(
        _route_key(r.start_lat, r.start_lng, r.end_lat, r.end_lng) + f"|{r.count}"
        for r in routes.itertuples()
    )


def is_road_map_stale(df: pd.DataFrame) -> tuple[bool, pd.DataFrame, str]:
    """Cheap check: returns (stale, unique_routes, current_fingerprint).

    Stale when the rental data's unique-routes set differs from the fingerprint
    saved alongside the last regenerated HTML, or when the HTML is missing.
    """
    routes = _unique_routes(df)
    current_fp = _fingerprint(routes)
    saved_fp = ROUTE_FINGERPRINT.read_text() if ROUTE_FINGERPRINT.exists() else ""
    stale = (saved_fp != current_fp) or (not ROAD_MAP_HTML.exists())
    return stale, routes, current_fp


def _load_geometry_cache() -> dict[str, list[list[float]]]:
    if ROUTE_GEOMETRY_CACHE.exists():
        try:
            return json.loads(ROUTE_GEOMETRY_CACHE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_geometry_cache(cache: dict[str, list[list[float]]]) -> None:
    ASSETS.mkdir(exist_ok=True)
    ROUTE_GEOMETRY_CACHE.write_text(json.dumps(cache))


def _fetch_osrm_geometry(
    slat: float, slon: float, elat: float, elon: float,
) -> list[list[float]] | None:
    """Single OSRM cycling-route call. Returns [[lat, lon], …] or None on any failure."""
    try:
        r = requests.get(
            OSRM_URL.format(slat=slat, slon=slon, elat=elat, elon=elon),
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("code") != "Ok":
            return None
        # GeoJSON gives [lon, lat]; folium wants [lat, lon].
        return [[lat, lon] for lon, lat in data["routes"][0]["geometry"]["coordinates"]]
    except (requests.RequestException, ValueError, KeyError):
        return None


def _build_folium_html(routes: pd.DataFrame, cache: dict[str, list[list[float]]]) -> str:
    """Render the dark-themed Folium map from cached geometries."""
    if routes.empty:
        return "<html><body><p>No route data available.</p></body></html>"

    m = folium.Map(
        location=[routes["start_lat"].mean(), routes["start_lng"].mean()],
        zoom_start=13,
        tiles="CartoDB dark_matter",
    )
    for r in routes.itertuples():
        if r.start_lat == r.end_lat and r.start_lng == r.end_lng:
            continue
        coords = cache.get(_route_key(r.start_lat, r.start_lng, r.end_lat, r.end_lng))
        if not coords:
            continue
        weight = min(2 + r.count * 0.3, 12)
        opacity = min(0.3 + r.count * 0.05, 0.9)
        folium.PolyLine(
            locations=coords, color="#00FFFF", weight=weight, opacity=opacity,
            tooltip=f"Trips on this route: {r.count}",
        ).add_to(m)

    return m.get_root().render()


def regenerate_road_map(routes: pd.DataFrame, fingerprint: str) -> dict:
    """Fetch any missing geometries from OSRM, rebuild the HTML, persist the fingerprint.

    Returns stats: {new_fetched, total_routes, failed_fetches}.
    """
    cache = _load_geometry_cache()
    new_fetched = 0
    failed = 0

    for r in routes.itertuples():
        if r.start_lat == r.end_lat and r.start_lng == r.end_lng:
            continue
        key = _route_key(r.start_lat, r.start_lng, r.end_lat, r.end_lng)
        if key in cache:
            continue
        geom = _fetch_osrm_geometry(r.start_lat, r.start_lng, r.end_lat, r.end_lng)
        if geom:
            cache[key] = geom
            new_fetched += 1
        else:
            failed += 1
        time.sleep(0.1)  # respect OSRM public-API rate limits

    _save_geometry_cache(cache)

    ASSETS.mkdir(exist_ok=True)
    ROAD_MAP_HTML.write_text(_build_folium_html(routes, cache))
    ROUTE_FINGERPRINT.write_text(fingerprint)

    # Map HTML changed on disk — invalidate the in-memory cache so the next read picks it up.
    load_road_map_html.clear()

    return {
        "new_fetched": new_fetched,
        "total_routes": len(routes),
        "failed_fetches": failed,
    }
