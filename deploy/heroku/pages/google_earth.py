import streamlit as st
from streamlit_folium import st_folium

import folium
from io import BytesIO
import base64


import json
import xml.etree.ElementTree as ET
import requests
from PIL import Image
import os

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

    def fetch_slack_image_as_base64(url, token, thumb_size=(150, 150)):
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
            img.thumbnail(thumb_size)
            buffered = BytesIO()
            img.save(buffered, format="JPEG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode()
            return f'<img src="data:image/jpeg;base64,{img_b64}" width="{thumb_size[0]}">' 
        except Exception as e:
            return "<i>Image preview unavailable</i>"

    import re
    def replace_slack_images_in_html(html, token):
        # Find all <img src="..."> tags
        def repl(match):
            url = match.group(1)
            if 'slack.com' in url:
                return fetch_slack_image_as_base64(url, token)
            return match.group(0)
        return re.sub(r'<img[^>]*src=["\']([^"\']+)["\'][^>]*>', repl, html or '')
    slack_token = os.environ.get('SLACK_BOT_TOKEN')
    for pm in placemarks:
        name = pm.find('kml:name', ns)
        desc = pm.find('kml:description', ns)
        point = pm.find('.//kml:Point', ns)
        coords = point.find('kml:coordinates', ns) if point is not None else None
        debug_lines.append(f"Placemark: {name.text if name is not None else ''}")
        description_html = desc.text if desc is not None else None
        if slack_token and description_html:
            description_html = replace_slack_images_in_html(description_html, slack_token)
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
                    "description": description_html
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
