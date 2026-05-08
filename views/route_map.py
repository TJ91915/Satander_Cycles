"""Route Map tab — embed the road-routed Folium map; auto-refresh when new trips arrive."""
from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from lib import (
    ROAD_MAP_HTML,
    is_road_map_stale,
    load_road_map_html,
    regenerate_road_map,
    road_map_mtime,
)


def render(df: pd.DataFrame) -> None:
    st.subheader("Road-routed cycle journeys across London")

    # Stale-check is cheap (a single file read + a string compare). Only the OSRM
    # call path is expensive — and that path only runs when new station pairs
    # appear in the rental log since the last regeneration.
    stale, routes, fingerprint = is_road_map_stale(df)

    if stale:
        with st.status("Updating route map with new data…", expanded=False) as status:
            stats = regenerate_road_map(routes, fingerprint)
            label = (
                f"Map refreshed — {stats['new_fetched']} new routes fetched, "
                f"{stats['total_routes']} total"
            )
            if stats["failed_fetches"]:
                label += f" ({stats['failed_fetches']} OSRM lookups failed, will retry next load)"
            status.update(label=label, state="complete")

    st.caption(
        f"Real road geometry via OSRM (not point-to-point straight lines). "
        f"Last regenerated: {road_map_mtime()}."
    )

    if not ROAD_MAP_HTML.exists():
        st.warning(
            "Road map HTML couldn't be generated — OSRM may be unreachable. "
            "It will retry on the next page load."
        )
        return

    components.html(load_road_map_html(), height=720, scrolling=False)
