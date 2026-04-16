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

def get_lat_lon_from_image(image_path):
    """Extract (lat, lon) from EXIF GPS data, or (None, None)."""
    try:
        img = Image.open(image_path)
        exif_bytes = img.info.get("exif", b"")
        exif_dict = piexif.load(exif_bytes)
        gps = exif_dict.get("GPS", {})
        if not gps:
            return None, None

        def _to_deg(value):
            d, m, s = value
            return d[0] / d[1] + m[0] / m[1] / 60 + s[0] / s[1] / 3600

        lat     = gps.get(piexif.GPSIFD.GPSLatitude)
        lat_ref = gps.get(piexif.GPSIFD.GPSLatitudeRef)
        lon     = gps.get(piexif.GPSIFD.GPSLongitude)
        lon_ref = gps.get(piexif.GPSIFD.GPSLongitudeRef)

        if lat and lat_ref and lon and lon_ref:
            latitude  = _to_deg(lat)  * (-1 if lat_ref == b"S" else 1)
            longitude = _to_deg(lon)  * (-1 if lon_ref == b"W" else 1)
            return latitude, longitude
        return None, None
    except Exception as e:
        print(f"Error reading EXIF data: {e}")
        return None, None


def get_all_image_coords(folder_path):
    """Walk a folder and return [(filepath, lat, lon)] for images with GPS data."""
    coords = []
    supported_exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    for root, _, files in os.walk(folder_path):
        for file in files:
            if os.path.splitext(file)[1].lower() in supported_exts:
                img_path = os.path.join(root, file)
                lat, lon = get_lat_lon_from_image(img_path)
                if lat is not None:
                    coords.append((img_path, lat, lon))
    return coords


def extract_zip_to_tempdir(zip_bytes):
    """
    Extract a zip file (as bytes) to a fresh temp directory.
    Returns the temp dir path — caller is responsible for cleanup.
    """
    tmp = tempfile.mkdtemp(prefix="img_gps_")
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        # Safety: skip any members with absolute or traversal paths
        for member in zf.infolist():
            member_path = os.path.realpath(os.path.join(tmp, member.filename))
            if not member_path.startswith(os.path.realpath(tmp)):
                continue
            zf.extract(member, tmp)
    return tmp


def image_thumbnail_html(filepath, width=120):
    """Return an <img> tag with a base64 thumbnail, or an error string."""
    try:
        img = Image.open(filepath)
        img.thumbnail((150, 150))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f'<img src="data:image/jpeg;base64,{b64}" width="{width}">'
    except Exception:
        return "<i>Image preview unavailable</i>"


def fetch_slack_image_as_base64(url, token, thumb_size=(150, 150)):
    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
        img.thumbnail(thumb_size)
        buf = BytesIO()
        img.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f'<img src="data:image/jpeg;base64,{b64}" width="{thumb_size[0]}">'
    except Exception:
        return "<i>Image preview unavailable</i>"


def replace_slack_images(html, token):
    """Swap Slack CDN <img> URLs for inline base64 thumbnails."""
    def repl(match):
        url = match.group(1)
        if "slack.com" in url:
            return fetch_slack_image_as_base64(url, token)
        return match.group(0)
    return re.sub(r'<img[^>]*src=["\']([^"\']+)["\'][^>]*>', repl, html or "")


def parse_kml(kml_text, slack_token=None):
    """
    Parse a KML string and return a list of feature dicts:
      { name, description, lat, lon }
    """
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    root = ET.fromstring(kml_text)
    features = []

    for pm in root.findall(".//kml:Placemark", ns):
        name_el  = pm.find("kml:name",        ns)
        desc_el  = pm.find("kml:description", ns)
        point    = pm.find(".//kml:Point",     ns)
        coords_el = point.find("kml:coordinates", ns) if point is not None else None

        if coords_el is None:
            continue  # skip placemarks without a Point

        lon, lat, *_ = coords_el.text.strip().split(",")
        desc_html = desc_el.text if desc_el is not None else ""

        if slack_token and desc_html:
            desc_html = replace_slack_images(desc_html, slack_token)

        features.append({
            "name":        name_el.text if name_el is not None else "",
            "description": desc_html,
            "lat":  float(lat),
            "lon":  float(lon),
        })

    return features


# ── map builders ─────────────────────────────────────────────────────────────

def build_map_from_image_coords(coords, default_location=(34.052235, -118.243683)):
    """Folium map with camera-pin markers for image GPS coords."""
    if coords:
        avg_lat = sum(r[1] for r in coords) / len(coords)
        avg_lon = sum(r[2] for r in coords) / len(coords)
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=15)
    else:
        m = folium.Map(location=default_location, zoom_start=13)

    for filepath, lat, lon in coords:
        file_url  = f"file://{filepath.replace(chr(92), '/')}"
        link_html = f'<a href="{file_url}" target="_blank">{os.path.basename(filepath)}</a>'
        thumb     = image_thumbnail_html(filepath)
        popup_html = f"<html><body>{link_html}<br>{thumb}</body></html>"
        iframe     = folium.IFrame(popup_html, width=200, height=200)
        folium.Marker(
            [lat, lon],
            popup=folium.Popup(iframe, max_width=220),
            tooltip=os.path.basename(filepath),
            icon=folium.Icon(color="red", icon="camera", prefix="fa"),
        ).add_to(m)

    return m


def build_map_from_kml_features(features):
    """Folium map with camera-pin markers for KML placemarks."""
    if features:
        avg_lat = sum(f["lat"] for f in features) / len(features)
        avg_lon = sum(f["lon"] for f in features) / len(features)
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=13)
    else:
        m = folium.Map(location=[20, 0], zoom_start=2)

    for feat in features:
        iframe = folium.IFrame(feat["description"] or feat["name"], width=300, height=200)
        folium.Marker(
            [feat["lat"], feat["lon"]],
            popup=folium.Popup(iframe, max_width=400),
            tooltip=feat["name"],
            icon=folium.Icon(color="red", icon="camera", prefix="fa"),
        ).add_to(m)

    return m


# ── Streamlit UI ──────────────────────────────────────────────────────────────

st.title("📍 Image GPS / KML Viewer")

tab1, tab2 = st.tabs(["🖼️ Image Folder (EXIF GPS)", "🗺️ KML Upload"])

# ── Tab 1: image folder / zip upload ─────────────────────────────────────────
with tab1:
    st.markdown("Upload a **ZIP file** containing images, or enter a local folder path.")

    uploaded_zip = st.file_uploader(
        "Upload ZIP of images", type=["zip"], key="zip_uploader",
        help="ZIP may contain subfolders. Only JPG/JPEG/PNG/TIF/TIFF images are scanned."
    )

    st.markdown("<div style='text-align:center;color:grey;margin:4px 0'>— or —</div>", unsafe_allow_html=True)

    folder = st.text_input("Local folder path (server-side):", "images", key="folder_input")

    col1, col2 = st.columns([1, 4])
    with col1:
        scan_btn = st.button("📍 Scan & Show Map", key="img_btn")

    if scan_btn:
        tmp_dir = None
        try:
            if uploaded_zip is not None:
                with st.spinner("Extracting ZIP…"):
                    tmp_dir = extract_zip_to_tempdir(uploaded_zip.read())
                scan_path = tmp_dir
                st.info(f"Extracted ZIP to temp folder. Scanning…")
            else:
                scan_path = folder

            with st.spinner("Scanning images for GPS data…"):
                st.session_state["img_coords"] = get_all_image_coords(scan_path)
                # Store thumbnails from temp dir as base64 before cleanup
                # (filepaths remain valid until end of request when tmp_dir is cleaned)
        finally:
            # Don't delete yet — filepaths are still needed for map rendering below
            # Store tmp_dir in session so we can clean it up on next run
            if tmp_dir:
                prev_tmp = st.session_state.get("img_tmp_dir")
                if prev_tmp and os.path.exists(prev_tmp):
                    shutil.rmtree(prev_tmp, ignore_errors=True)
                st.session_state["img_tmp_dir"] = tmp_dir

    if "img_coords" in st.session_state:
        coords = st.session_state["img_coords"]
        st.write(f"Found **{len(coords)}** image(s) with GPS data.")
        if coords:
            m = build_map_from_image_coords(coords)
            st_folium(m, use_container_width=True, height=800, returned_objects=[])
        else:
            st.warning("No images with GPS data found.")

# ── Tab 2: KML upload ─────────────────────────────────────────────────────────
with tab2:
    uploaded_kml = st.file_uploader("Upload a KML file", type=["kml"])

    if uploaded_kml:
        kml_text = uploaded_kml.read().decode("utf-8")
        slack_token = os.environ.get("SLACK_BOT_TOKEN")

        with st.spinner("Parsing KML…"):
            try:
                features = parse_kml(kml_text, slack_token=slack_token)
            except ET.ParseError as exc:
                st.error(f"Could not parse KML: {exc}")
                features = []

        if features:
            st.success(f"Loaded **{len(features)}** placemark(s).")
            m = build_map_from_kml_features(features)
            st_folium(m, use_container_width=True, height=800, returned_objects=[])

            # Download link for the uploaded KML
            b64 = base64.b64encode(kml_text.encode()).decode()
            st.markdown(
                f'<a href="data:file/kml;base64,{b64}" download="{uploaded_kml.name}">⬇️ Download KML file</a>',
                unsafe_allow_html=True,
            )

            with st.expander("Debug – parsed placemarks"):
                for f in features:
                    st.write(f"**{f['name']}** — lat {f['lat']:.5f}, lon {f['lon']:.5f}")
        else:
            st.error("No Point placemarks found in the KML file.")