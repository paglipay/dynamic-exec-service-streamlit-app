import streamlit as st
from streamlit_folium import st_folium
import folium
from io import BytesIO
import base64

st.title('Google Earth-like KML Viewer')

uploaded_file = st.file_uploader('Upload KML file', type=['kml'])

m = folium.Map(location=[20,0], zoom_start=2)

if uploaded_file:
    kml_data = uploaded_file.read().decode('utf-8')
    folium.Kml(data=kml_data).add_to(m)
    st.success('KML file loaded')

    # Provide download link for the uploaded file
    b64 = base64.b64encode(kml_data.encode()).decode()
    href = f'<a href="data:file/kml;base64,{b64}" download="downloaded.kml">Download KML file</a>'
    st.markdown(href, unsafe_allow_html=True)

st_folium(m, width=700, height=500)
