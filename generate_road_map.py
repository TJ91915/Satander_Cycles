import pandas as pd
import requests
import time
import folium
import os

def generate_road_route_map():
    # File paths (Assuming this script is run in the same folder as your CSV)
    input_csv = "Bike account rental history TfL Restricted.csv"
    output_html = "london_road_routes_map.html"
    
    if not os.path.exists(input_csv):
        print(f"Error: Could not find '{input_csv}'. Please ensure it is in the same folder.")
        return

    print("Loading data...")
    df = pd.read_csv(input_csv, encoding='latin1')
    
    # Ensure coordinates are numeric
    coords = ['Start station lat', 'Start station long', 'End station lat', 'End station long']
    for col in coords:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    df_clean = df.dropna(subset=coords)
    
    # Group by unique station combinations to get trip frequencies 
    # This prevents us from spamming the routing API for the exact same route
    print("Finding unique routes...")
    route_counts = df_clean.groupby(coords).size().reset_index(name='count')
    
    # Initialize an interactive dark-themed Folium Map centered on London
    center_lat = df_clean['Start station lat'].mean()
    center_lon = df_clean['Start station long'].mean()
    # Esri dark canvas: keyless (CARTO tiles now require an API key)
    m = folium.Map(
        location=[center_lat, center_lon], zoom_start=13, max_zoom=16,
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
        attr='Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors',
    )
    
    print(f"Fetching physical road routes for {len(route_counts)} unique station pairs...")
    print("This might take a couple of minutes as we communicate with the routing API...")
    
    for index, row in route_counts.iterrows():
        slat, slon = row['Start station lat'], row['Start station long']
        elat, elon = row['End station lat'], row['End station long']
        freq = row['count']
        
        # Skip if start and end are exactly the same (circular trips)
        if slat == elat and slon == elon:
            continue
            
        # Call OSRM public API to get the cycling road route
        url = f"http://router.project-osrm.org/route/v1/cycling/{slon},{slat};{elon},{elat}?overview=full&geometries=geojson"
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data['code'] == 'Ok':
                    # Extract the road coordinates
                    # GeoJSON provides [longitude, latitude], but Folium needs [latitude, longitude]
                    route_coords = data['routes'][0]['geometry']['coordinates']
                    folium_coords = [(lat, lon) for lon, lat in route_coords]
                    
                    # Heatmap effect: determine thickness/opacity based on how many times you rode this
                    weight = min(2 + (freq * 0.3), 12) 
                    opacity = min(0.3 + (freq * 0.05), 0.9)
                    
                    # Draw the route on the map
                    folium.PolyLine(
                        locations=folium_coords,
                        color='#00FFFF', # Cyan
                        weight=weight,
                        opacity=opacity,
                        tooltip=f"Trips taken on this route: {freq}"
                    ).add_to(m)
            
            # Sleep briefly to respect the routing API's rate limits
            time.sleep(0.1)
            
            if (index + 1) % 50 == 0:
                print(f"Processed {index + 1} / {len(route_counts)} unique routes...")
                
        except Exception as e:
            print(f"Warning: Failed to fetch route {index}: {e}")
            
    print(f"Saving interactive map to '{output_html}'...")
    m.save(output_html)
    print("Success! Double-click 'london_road_routes_map.html' to open it in your browser.")

if __name__ == "__main__":
    generate_road_route_map()