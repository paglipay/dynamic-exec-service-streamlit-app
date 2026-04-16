import os
import base64
import tempfile
import shutil
import zipfile
from datetime import datetime
from io import BytesIO

import requests
from PIL import Image
import piexif
import streamlit as st
from streamlit_folium import st_folium
import folium

# ── Page Configuration ───────────────────────────────────────────────────────
st.set_page_config(page_title="Photo Path Tracker", layout="wide")

# ── EXIF Extraction Logic ────────────────────────────────────────────────────

def get_exif_data(image_path):
    """Extracts lat, lon, heading, and timestamp from an image."""
    try:
        img = Image.open(image_path)
        exif_bytes = img.info.get("exif", b"")
        if not exif_bytes:
            return None, None, None, None
            
        exif_dict = piexif.load(exif_bytes)
        gps = exif_dict.get("GPS", {})
        exif = exif_dict.get("Exif", {})

        # 1. Coordinates
        def _to_deg(value):
            d, m, s = value
            return d[0] / d[1] + m[0] / m[1] / 60 + s[0] / s[1] / 3600

        lat = gps.get(piexif.GPSIFD.GPSLatitude)
        lat_ref = gps.get(piexif.GPSIFD.GPSLatitudeRef)
        lon = gps.get(piexif.GPSIFD.GPSLongitude)
        lon_ref = gps.get(piexif.GPSIFD.GPSLongitudeRef)

        if not (lat and lat_ref and lon and lon_ref):
            return None, None, None, None

        latitude = _to_deg(lat) * (-1 if lat_ref == b"S" else 1)
        longitude = _to_deg(lon) * (-1 if lon_ref == b"W" else 1)

        # 2. Camera Direction (Heading)
        direction = gps.get(piexif.GPSIFD.GPSImgDirection)
        heading = direction[0] / direction[1] if direction else None

        # 3. Timestamp
        time_str = exif.get(piexif.ExifIFD.DateTimeOriginal)
        timestamp = None
        if time_str:
            try:
                timestamp = datetime.strptime(time_str.decode("utf-8"), "%Y:%m:%d %H:%M:%S")
            except:
                pass

        return latitude, longitude, heading, timestamp
    except:
        return None, None, None, None

def process_images(folder_path):
    """Scans folder and returns a sorted list of image metadata."""
    data = []
    exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    for root, _, files in os.walk(folder_path):
        for file in files:
            if os.path.splitext(file)[1].lower() in exts:
                path = os.path.join(root, file)
                lat, lon, heading, time = get_exif_data(path)
                if lat is not None:
                    data.append({
                        "path": path, "lat": lat, "lon": lon, 
                        "heading": heading, "time": time, "name": file
                    })
    # Sort chronologically
    data.sort(key=lambda x: x["time"] if x["time"] else datetime.min)
    return data

# ── Visual Helpers ───────────────────────────────────────────────────────────

def get_thumb_base64(filepath):
    """Generates a base64 thumbnail for map popups."""
    try:
        img = Image.open(filepath)
        img.thumbnail((150, 150))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        return base64.b64encode(buf.getvalue()).decode()
    except:
        return None

def get_direction_icon(heading):
    """Creates a rotated SVG arrow if heading exists, else a standard icon."""