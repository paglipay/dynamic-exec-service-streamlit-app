import streamlit as st
from streamlit_folium import st_folium

import folium
from io import BytesIO
import base64
from fastkml import kml
import json

st.title('Google Earth-like KML Viewer')

uploaded_file = st.file_uploader('Upload KML file', type=['kml'])

m = folium.Map(location=[20,0], zoom_start=2)

if uploaded_file:
    kml_data = uploaded_file.read().decode('utf-8')
    k = kml.KML()
    k.from_string(kml_data.encode('utf-8'))
    # Recursively extract all features with geometry from KML
    def extract_features(obj, geojson_features):
        # Recursively extract all Placemarks with geometry
        if hasattr(obj, 'features') and obj.features:
            for f in obj.features:
                extract_features(f, geojson_features)
        # Only add if it's a Placemark with geometry
        if hasattr(obj, 'geometry') and obj.geometry:
            props = {"name": getattr(obj, 'name', None)}
            # Add description if available
            if hasattr(obj, 'description') and obj.description:
                props["description"] = obj.description
            geojson_features.append({
                "type": "Feature",
                "geometry": json.loads(obj.geometry.json),
                "properties": props
            })

    geojson_features = []
    for feature in k.features:
        extract_features(feature, geojson_features)

    if geojson_features:
        geojson = {"type": "FeatureCollection", "features": geojson_features}
        folium.GeoJson(geojson, name="KML Data").add_to(m)
        st.success('KML file loaded and displayed as GeoJSON')
    else:
        st.error('No valid features found in KML file.')

    # Provide download link for the uploaded file
    b64 = base64.b64encode(kml_data.encode()).decode()
    href = f'<a href="data:file/kml;base64,{b64}" download="downloaded.kml">Download KML file</a>'
    st.markdown(href, unsafe_allow_html=True)

st_folium(m, width=700, height=500)
