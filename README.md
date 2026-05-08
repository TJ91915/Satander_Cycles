# Santander Cycles Dashboard

Streamlit dashboard for 7+ years of London Santander Cycles rentals, read live from Google Sheets.

## Run locally

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/streamlit run app.py
```

Auth: put `service-account-key.json` in the project root (gitignored), or create `.streamlit/secrets.toml` (see below). The app tries Streamlit secrets first, then falls back to the key file. The service account email needs Viewer access on all three Sheets.

## Deploy to Streamlit Community Cloud

1. Push to GitHub (public is fine — secrets aren't committed).
2. On [share.streamlit.io](https://share.streamlit.io), "New app" → point at the repo, main branch, `app.py`.
3. In the app's **Settings → Secrets**, paste the contents of `.streamlit/secrets.toml.example`, filled in from your `service-account-key.json`.
4. Deploy.

## Data sources

| Sheet | ID | Tab | Used for |
|---|---|---|---|
| Bike Rental | `1UlnOyrkfry7tpxhxWqWLP3pHmzTOV52qKZhGpcFABVk` | first | trip log — every chart in Overview / Trends / Stations / Bikes |
| Dock Locations | `1eAFmEryZF5xUOxBjkFe2iZRDkWa-Us4zMfGfKSNhMfY` | first | station coordinates (used by road-map regen script) |
| Payments | `1GgAAjcPmsH_bv_bu2_UH8cV015Rh2mloqh9YoyHyMhk` | first | costs (deferred — Payments tab placeholder) |

Sheet reads are cached for 2 hours (`CACHE_TTL` in `lib.py`). To force a refresh, use Streamlit's menu → "Clear cache".

## Route Map

The Route Map tab embeds a Folium map with OSRM-routed cycle paths (real road geometry, not straight lines). On each page load, the dashboard fingerprints the unique start→end coordinate pairs in the Rental Log; if it differs from the last regenerated map, OSRM is called for any **new** routes only and the HTML is rebuilt. Geometries are cached locally in `assets/route_geometry_cache.json`.

The map files are gitignored on purpose — the repo carries no trip data. First page load on a fresh deploy takes ~20–30 seconds while OSRM is queried; subsequent loads are instant.

## Excluding bikes

`lib.EXCLUDED_BIKE_IDS` is a frozen set of bike IDs to drop from every calculation (KPIs, charts, the road map). Currently contains `20548` (stolen mid-rental — its trip duration was days, not minutes, and broke the time-based charts). Add new IDs to the set as needed.

## Tabs

- **Overview** — KPIs, yearly rides with classic/ebike split, bike-model breakdown
- **Trends** — monthly rides, monthly hours (y-axis capped to ignore single-day outliers), year×month YoY heatmap
- **Route Map** — embedded road-routed Folium map, auto-refreshes when new trips appear
- **Stations** — top 15 most-used stations + top 20 routes + start/end split
- **Bikes** — most-rides / most-time / longest-span KPIs + top 10 IDs + stacked rentals over time (Day/Month/Year toggle) + per-bike summary table
- **Payments** — placeholder (next iteration)
