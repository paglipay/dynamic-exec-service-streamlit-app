import streamlit as st
from streamlit_folium import st_folium

import folium
from io import BytesIO
import base64

import json
import xml.etree.ElementTree as ET

st.title('Google Earth-like KML Viewer')

uploaded_file = st.file_uploader('Upload KML file', type=['kml'])

m = folium.Map(location=[20,0], zoom_start=2)


if uploaded_file:
    kml_data = uploaded_file.read().decode('utf-8')
    # Parse KML using ElementTree for maximum compatibility
    ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    root = ET.fromstring(kml_data)
    geojson_features = []
    placemarks = root.findall('.//kml:Placemark', ns)
    debug_lines = []
    for pm in placemarks:
        name = pm.find('kml:name', ns)
        desc = pm.find('kml:description', ns)
        point = pm.find('.//kml:Point', ns)
        coords = point.find('kml:coordinates', ns) if point is not None else None
        debug_lines.append(f"Placemark: {name.text if name is not None else ''}")
        if coords is not None:
            lon, lat, *_ = coords.text.strip().split(',')
            geojson_features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(lon), float(lat)]
                },
                "properties": {
                    "name": name.text if name is not None else None,
                    "description": desc.text if desc is not None else None
                }
            })
    with st.expander("Show parsed KML structure (debug)"):
        st.text("\n".join(debug_lines))

    if geojson_features:
        geojson = {"type": "FeatureCollection", "features": geojson_features}
        popup = folium.GeoJsonPopup(fields=["description"], labels=False, parse_html=True, max_width=400)
        folium.GeoJson(
            geojson,
            name="KML Data",
            popup=popup
        ).add_to(m)
        st.success('KML file loaded and displayed as GeoJSON')
    else:
        st.error('No valid features found in KML file.')

    # Provide download link for the uploaded file
    b64 = base64.b64encode(kml_data.encode()).decode()
    href = f'<a href="data:file/kml;base64,{b64}" download="downloaded.kml">Download KML file</a>'
    st.markdown(href, unsafe_allow_html=True)

st_folium(m, width=700, height=500)
