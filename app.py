"""Santander Cycles dashboard — single-page entry with tabs."""
import streamlit as st

from lib import load_rentals
from views import bikes, overview, payments, route_map, stations, trends

st.set_page_config(
    page_title="Santander Cycles",
    page_icon="🚲",
    layout="wide",
)

# Pre-warm the rental loader once. Every tab below shares the resulting frame
# (cached at 2h TTL — see lib.CACHE_TTL).
df = load_rentals()

st.title("🚲 Santander Cycles")

caption = (
    f"{len(df):,} trips • "
    f"{df['start_dt'].min():%b %Y} – {df['start_dt'].max():%b %Y}"
)
excluded = df.attrs.get("excluded_trip_count", 0)
if excluded:
    bikes_list = ", ".join(df.attrs.get("excluded_bike_ids", []))
    caption += f" • {excluded} trip{'s' if excluded != 1 else ''} excluded (bike {bikes_list})"
st.caption(caption)

t_overview, t_trends, t_map, t_stations, t_bikes, t_payments = st.tabs([
    "Overview", "Trends", "Route Map", "Stations", "Bikes", "Payments",
])

with t_overview:
    overview.render(df)
with t_trends:
    trends.render(df)
with t_map:
    route_map.render(df)
with t_stations:
    stations.render(df)
with t_bikes:
    bikes.render(df)
with t_payments:
    payments.render()
