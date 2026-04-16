import os
import re
import base64
import tempfile
import shutil
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO

import requests
from PIL import Image
import piexif
import streamlit as st
from streamlit_folium import st_folium
import folium

st.set_page_config(layout="wide")

# ── helpers ──────────────────────────────────────────────────────────────────

def get_exif_data_from_image(image_path):
    """Extract (lat, lon, direction) from EXIF GPS data."""
    try:
        img = Image.open(image_path)
        exif_bytes = img.info.get("exif", b"")
        if not exif_bytes:
            return None, None, None
            
        exif_dict = piexif.load(exif_bytes)
        gps = exif_dict.get("GPS", {})
        if not gps:
            return None, None, None

        def _to_deg(value):
            d, m, s = value
            return d[0] / d[1] + m[0] / m[1] / 60 + s[0] / s[1] / 3600

        lat      = gps.get(piexif.GPSIFD.GPSLatitude)
        lat_ref  = gps.get(piexif.GPSIFD.GPSLatitudeRef)
        lon      = gps.get(piexif.GPSIFD.GPSLongitude)
        lon_ref  = gps.get(piexif.GPSIFD.GPSLongitudeRef)
        
        # Extract Camera Direction (Bearing)
        direction = gps.get(piexif.GPSIFD.GPSImgDirection)
        heading = None
        if direction:
            heading = direction[0] / direction[1]

        if lat and lat_ref and lon and lon_ref:
            latitude  = _to_deg(lat)  * (-1 if lat_ref == b"S" else 1)
            longitude = _to_deg(lon)  * (-1 if lon_ref == b"W" else 1)
            return latitude, longitude, heading
            
        return None, None, None
    except Exception:
        return None, None, None

def get_all_image_coords(folder_path):
    """Walk folder and return [(filepath, lat, lon, heading)]."""
    coords = []
    supported_exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    for root, _, files in os.walk(folder_path):
        for file in files:
            if os.path.splitext(file)[1].lower() in supported_exts:
                img_path = os.path.join(root, file)
                lat, lon, heading = get_exif_data_from_image(img_path)
                if lat is not None:
                    coords.append((img_path, lat, lon, heading))
    return coords

def extract_zip_to_tempdir(zip_bytes):
    tmp = tempfile.mkdtemp(prefix="img_gps_")
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        for member in zf.infolist():
            member_path = os.path.realpath(os.path.join(tmp, member.filename))
            if not member_path.startswith(os.path.realpath(tmp)):
                continue
            zf.extract(member, tmp)
    return tmp

def image_thumbnail_html(filepath, width=120):
    try:
        img = Image.open(filepath)
        img.thumbnail((150, 150))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f'<img src="data:image/jpeg;base64,{b64}" width="{width}">'
    except Exception:
        return "<i>Image preview unavailable</i>"

# ── map builders ─────────────────────────────────────────────────────────────

def get_direction_icon(heading):
    """Returns a rotated arrow SVG if heading exists, else a standard marker."""
    if heading is None:
        return folium.Icon(color="red", icon="camera", prefix="fa")
    
    # Custom SVG Arrow for direction
    svg_icon = f"""
    <div style="transform: rotate({heading}deg); width: 30px; height: 30px;">
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 2L4.5 20.29L5.21 21L12 18L18.79 21L19.5 20.29L12 2Z" fill="#ff4b4b" stroke="white" stroke-width="1"/>
        </svg>
    </div>
    """
    return folium.DivIcon(html=svg_icon, icon_size=(30, 30), icon_anchor=(15, 15))

def build_map_from_image_coords(coords):
    if coords:
        avg_lat = sum(r[1] for r in coords) / len(coords)
        avg_lon = sum(r[2] for r in coords) / len(coords)
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=15, tiles=None, max_zoom=21)
    else:
        m = folium.Map(location=(34.0522, -118.2437), zoom_start=13, tiles=None, max_zoom=21)

    for filepath, lat, lon, heading in coords:
        thumb = image_thumbnail_html(filepath)
        popup_html = f"<b>{os.path.basename(filepath)}</b><br>{thumb}"
        if heading is not None:
            popup_html += f"<br>Heading: {heading:.1f}°"
            
        iframe = folium.IFrame(popup_html, width=180, height=200)
        
        # Add the directional arrow
        folium.Marker(
            [lat, lon],
            popup=folium.Popup(iframe, max_width=220),
            tooltip=os.path.basename(filepath),
            icon=get_direction_icon(heading),
        ).add_to(m)

    # Re-inject your tile switcher here if needed
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite", max_zoom=21
    ).add_to(m)
    
    return m

# ── Streamlit UI (Condensed for brevity) ──────────────────────────────────────

st.title("📍 Image GPS & Direction Viewer")

uploaded_zip = st.file_uploader("Upload ZIP of images", type=["zip"])

if uploaded_zip:
    tmp_dir = extract_zip_to_tempdir(uploaded_zip.read())
    coords = get_all_image_coords(tmp_dir)
    
    if coords:
        st.success(f"Mapped {len(coords)} images.")
        m = build_map_from_image_coords(coords)
        st_folium(m, use_container_width=True, height=700)
    else:
        st.warning("No GPS data found.")
    
    shutil.rmtree(tmp_dir, ignore_errors=True)