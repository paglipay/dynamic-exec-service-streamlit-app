import os
import re
import base64
import tempfile
import shutil
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO

import pandas as pd
import requests
from PIL import Image
import piexif
import streamlit as st
from streamlit_folium import st_folium
import folium
from branca.element import MacroElement
from jinja2 import Template


class _RenumberButton(MacroElement):
    """Auto-renumbers visible numbered pins when a layer is toggled. Also adds Check/Uncheck All."""
    _template = Template("""
        {% macro script(this, kwargs) %}
        (function(){
          function renumber(){
            var pins=[];
            {{this._map_var}}.eachLayer(function(layer){
              if(typeof layer.eachLayer==='function'){
                layer.eachLayer(function(marker){
                  if(marker._icon){
                    var d=marker._icon.querySelector('[data-pin-idx]');
                    if(d) pins.push({orig:parseInt(d.getAttribute('data-pin-idx')),div:d});
                  }
                });
              }
            });
            pins.sort(function(a,b){return a.orig-b.orig;});
            pins.forEach(function(p,i){p.div.textContent=i+1;});
          }
          {{this._map_var}}.on('overlayadd overlayremove', function(){
            setTimeout(renumber, 50);
          });

          function getOverlays(){
            var overlays=[];
            {{this._map_var}}.eachLayer(function(layer){
              if(typeof layer.eachLayer==='function'){
                overlays.push(layer);
              }
            });
            return overlays;
          }
          function setAll(show){
            getOverlays().forEach(function(layer){
              if(show){
                if(!{{this._map_var}}.hasLayer(layer)){
                  {{this._map_var}}.addLayer(layer);
                  {{this._map_var}}.fire('overlayadd',{layer:layer});
                }
              } else {
                if({{this._map_var}}.hasLayer(layer)){
                  {{this._map_var}}.removeLayer(layer);
                  {{this._map_var}}.fire('overlayremove',{layer:layer});
                }
              }
            });
            setTimeout(renumber,80);
          }

          // ── floating overlay for Get List ───────────────────────────
          var overlay=document.createElement('div');
          overlay.style.cssText='display:none;position:absolute;top:50%;left:50%;'
            +'transform:translate(-50%,-50%);z-index:9999;background:white;'
            +'border:2px solid #666;border-radius:6px;padding:12px 14px;'
            +'box-shadow:0 4px 12px rgba(0,0,0,.4);min-width:220px;font-family:monospace;';
          overlay.innerHTML="<div style='font-size:11px;color:#555;margin-bottom:6px;'>"
            +"Visible pin numbers &mdash; Copy, then paste into the <b>Paste list</b> box above the table:</div>"
            +"<input id='_pinListInput' readonly style='width:100%;font-size:14px;font-weight:bold;"
            +"padding:4px;border:1px solid #aaa;border-radius:3px;box-sizing:border-box;'>"
            +"<div style='text-align:right;margin-top:8px;gap:6px;display:flex;justify-content:flex-end;'>"
            +"<button id='_pinListCopy' style='padding:3px 10px;cursor:pointer;background:#1a73e8;color:white;border:none;border-radius:3px;'>&#128203; Copy</button>"
            +"<button id='_pinListClose' style='padding:3px 10px;cursor:pointer;'>Close</button></div>";
          // Append to the map container so it's positioned relative to the map
          {{this._map_var}}.getContainer().style.position='relative';
          {{this._map_var}}.getContainer().appendChild(overlay);
          document.getElementById('_pinListClose').addEventListener('click',function(){
            overlay.style.display='none';
          });
          document.getElementById('_pinListCopy').addEventListener('click',function(){
            var inp=document.getElementById('_pinListInput');
            inp.select();
            navigator.clipboard.writeText(inp.value).then(function(){
              var btn=document.getElementById('_pinListCopy');
              btn.textContent='Copied!';
              setTimeout(function(){btn.innerHTML='&#128203; Copy';},1500);
            });
          });

          function getVisibleOriginals(){
            var nums=[];
            {{this._map_var}}.eachLayer(function(layer){
              if(typeof layer.eachLayer==='function'){
                layer.eachLayer(function(marker){
                  if(marker._icon){
                    var d=marker._icon.querySelector('[data-pin-idx]');
                    if(d) nums.push(parseInt(d.getAttribute('data-pin-idx')));
                  }
                });
              }
            });
            nums.sort(function(a,b){return a-b;});
            return nums;
          }

          var btnStyle='padding:4px 8px;cursor:pointer;background:white;font-size:12px;'
            +'font-weight:bold;border:1px solid rgba(0,0,0,0.3);white-space:nowrap;';
          var CheckAllCtrl=L.Control.extend({
            options:{position:'bottomright'},
            onAdd:function(){
              var div=L.DomUtil.create('div','leaflet-bar');
              div.style.cssText='display:flex;flex-direction:row;box-shadow:0 1px 5px rgba(0,0,0,.4);';
              var btnOn=L.DomUtil.create('button','',div);
              btnOn.innerHTML='&#9745; Check All';
              btnOn.style.cssText=btnStyle+'border-radius:4px 0 0 4px;border-right:none;';
              var btnOff=L.DomUtil.create('button','',div);
              btnOff.innerHTML='&#9744; Uncheck All';
              btnOff.style.cssText=btnStyle+'border-radius:0 0 0 0;border-right:none;';
              var btnList=L.DomUtil.create('button','',div);
              btnList.innerHTML='&#128203; Get List';
              btnList.style.cssText=btnStyle+'border-radius:0 4px 4px 0;';
              L.DomEvent.on(btnOn,'click',function(e){L.DomEvent.stopPropagation(e);setAll(true);});
              L.DomEvent.on(btnOff,'click',function(e){L.DomEvent.stopPropagation(e);setAll(false);});
              L.DomEvent.on(btnList,'click',function(e){
                L.DomEvent.stopPropagation(e);
                var nums=getVisibleOriginals();
                var inp=document.getElementById('_pinListInput');
                inp.value=nums.join(',');
                overlay.style.display='block';
                setTimeout(function(){inp.select();},50);
              });
              return div;
            }
          });
          new CheckAllCtrl().addTo({{this._map_var}});
        })();
        {% endmacro %}
    """)

    def __init__(self, map_var):
        super().__init__()
        self._map_var = map_var


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


def image_fullsize_html(filepath, max_px=800):
    """Return an <img> tag with a base64 full-size image (capped at max_px), or an error string."""
    try:
        img = Image.open(filepath)
        img.thumbnail((max_px, max_px))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90)
        b64 = base64.b64encode(buf.getvalue()).decode()
        w, h = img.size
        return f'<img src="data:image/jpeg;base64,{b64}" style="max-width:100%;height:auto" width="{w}" height="{h}">'
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

SATELLITE_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
SATELLITE_ATTR  = "Esri"


def _add_tile_layers(m):
    """Add satellite + street tile layers with a switcher control."""
    folium.TileLayer(
        tiles=SATELLITE_TILES,
        attr=SATELLITE_ATTR,
        name="Satellite",
        overlay=False,
        control=True,
        max_zoom=21,
        max_native_zoom=19,
    ).add_to(m)
    folium.TileLayer(
        tiles="OpenStreetMap",
        name="Street Map",
        overlay=False,
        control=True,
        max_zoom=21,
        max_native_zoom=19,
    ).add_to(m)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    map_var = m.get_name()
    m.get_root().header.add_child(folium.Element(
        "<style>"
        ".leaflet-control-layers-list {"
        "  max-height: 40vh;"
        "  overflow-y: auto;"
        "}"
        "</style>"
    ))
    _RenumberButton(map_var).add_to(m)


def build_map_from_image_coords(coords, default_location=(34.052235, -118.243683)):
    """Folium map with camera-pin markers for image GPS coords."""
    if coords:
        avg_lat = sum(r[1] for r in coords) / len(coords)
        avg_lon = sum(r[2] for r in coords) / len(coords)
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=15, tiles=SATELLITE_TILES, attr=SATELLITE_ATTR, max_zoom=21)
    else:
        m = folium.Map(location=default_location, zoom_start=13, tiles=SATELLITE_TILES, attr=SATELLITE_ATTR, max_zoom=21)

    for idx, (filepath, lat, lon) in enumerate(coords, start=1):
        file_url  = f"file://{filepath.replace(chr(92), '/')}"
        link_html = f'<a href="{file_url}" target="_blank">{os.path.basename(filepath)}</a>'
        thumb     = image_thumbnail_html(filepath)
        full_img  = image_fullsize_html(filepath)
        popup_html = (
            f'<div style="font-family:sans-serif;text-align:center;padding:4px">'
            f'<b style="font-size:13px">{idx}. {os.path.basename(filepath)}</b><br>'
            f'<div style="margin-top:6px">{full_img}</div>'
            f'<div style="margin-top:4px">{link_html}</div>'
            f'</div>'
        )
        fg = folium.FeatureGroup(name=f"{idx}. {os.path.basename(filepath)}", show=True)
        hover_html = (
            f'<div style="font-family:sans-serif;font-size:12px;max-width:160px">'
            f'<b>{idx}. {os.path.basename(filepath)}</b><br>{thumb}'
            f'</div>'
        )
        folium.Marker(
            [lat, lon],
            popup=folium.Popup(popup_html, max_width=860),
            tooltip=folium.Tooltip(hover_html, sticky=True),
            icon=folium.DivIcon(
                html=f'<div data-pin-idx="{idx}" style="'
                     'background:crimson;color:white;font-weight:bold;font-size:12px;'
                     'width:26px;height:26px;line-height:26px;text-align:center;'
                     'border-radius:50%;border:2px solid white;'
                     f'box-shadow:0 1px 3px rgba(0,0,0,.5)">{idx}</div>',
                icon_size=(26, 26),
                icon_anchor=(13, 13),
            ),
        ).add_to(fg)
        fg.add_to(m)

    _add_tile_layers(m)
    return m


def build_map_from_kml_features(features):
    """Folium map with camera-pin markers for KML placemarks."""
    if features:
        avg_lat = sum(f["lat"] for f in features) / len(features)
        avg_lon = sum(f["lon"] for f in features) / len(features)
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=13, tiles=SATELLITE_TILES, attr=SATELLITE_ATTR, max_zoom=21)
    else:
        m = folium.Map(location=[20, 0], zoom_start=2, tiles=SATELLITE_TILES, attr=SATELLITE_ATTR, max_zoom=21)

    for idx, feat in enumerate(features, start=1):
        iframe = folium.IFrame(feat["description"] or feat["name"], width=300, height=200)
        fg = folium.FeatureGroup(name=f"{idx}. {feat['name']}", show=True)
        hover_html = (
            f'<div style="font-family:sans-serif;font-size:12px;max-width:220px">'
            f'<b>{idx}. {feat["name"]}</b>'
            + (f'<hr style="margin:4px 0">{feat["description"]}' if feat["description"] else '')
            + '</div>'
        )
        folium.Marker(
            [feat["lat"], feat["lon"]],
            popup=folium.Popup(iframe, max_width=400),
            tooltip=folium.Tooltip(hover_html, sticky=True),
            icon=folium.DivIcon(
                html=f'<div data-pin-idx="{idx}" style="'
                     'background:crimson;color:white;font-weight:bold;font-size:12px;'
                     'width:26px;height:26px;line-height:26px;text-align:center;'
                     'border-radius:50%;border:2px solid white;'
                     f'box-shadow:0 1px 3px rgba(0,0,0,.5)">{idx}</div>',
                icon_size=(26, 26),
                icon_anchor=(13, 13),
            ),
        ).add_to(fg)
        fg.add_to(m)

    _add_tile_layers(m)
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
                st.session_state["img_coords"] = sorted(
                    get_all_image_coords(scan_path),
                    key=lambda r: os.path.basename(r[0]).lower()
                )
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
            # ── Persist include-flags; reset when the file list changes ──────
            coord_key = tuple(os.path.basename(fp) for fp, _, __ in coords)
            if st.session_state.get("img_coord_key") != coord_key:
                st.session_state["img_coord_key"] = coord_key
                st.session_state["img_include"] = [False] * len(coords)
                st.session_state.pop("pin_editor", None)
                st.session_state["pin_list_input"] = ""

            # ── Paste-list input: override checkboxes from map's Get List ─
            paste_raw = st.text_input(
                "Paste list (from map 📋 Get List):",
                key="pin_list_input",
                placeholder="e.g. 1,3,5,7  — then press Enter",
            )
            if paste_raw.strip():
                try:
                    chosen = {int(x.strip()) for x in paste_raw.split(",") if x.strip()}
                    include_flags = [((i + 1) in chosen) for i in range(len(coords))]
                    st.session_state["img_include"] = include_flags
                    st.session_state.pop("pin_editor", None)
                except ValueError:
                    st.warning("List must be comma-separated numbers, e.g. 1,3,5")
                    include_flags = list(st.session_state["img_include"])
            else:
                # Pre-apply any pending editor delta so Renamed As is up-to-date
                include_flags = list(st.session_state["img_include"])
                editor_delta = st.session_state.get("pin_editor") or {}
                for row_str, changes in (editor_delta.get("edited_rows") or {}).items():
                    row_idx = int(row_str)
                    if "Include" in changes and row_idx < len(include_flags):
                        include_flags[row_idx] = changes["Include"]
                st.session_state["img_include"] = include_flags

            # Compute Renamed As: sequential among checked rows, in order
            checked_indices = [i for i, v in enumerate(include_flags) if v]
            n_checked = len(checked_indices)
            pad = max(2, len(str(n_checked))) if n_checked else 2
            renamed_as = ["—"] * len(coords)
            for rank, idx in enumerate(checked_indices, start=1):
                fp = coords[idx][0]
                renamed_as[idx] = f"{str(rank).zfill(pad)}{os.path.splitext(fp)[1].lower()}"

            edit_df = pd.DataFrame([
                {
                    "Include": include_flags[i],
                    "#": i + 1,
                    "File": os.path.basename(fp),
                    "Renamed As": renamed_as[i],
                    "Latitude": round(lat, 6),
                    "Longitude": round(lon, 6),
                }
                for i, (fp, lat, lon) in enumerate(coords)
            ])

            st.caption("Use the map layer control (top-right) to find pins. Click 📋 Get List on the map to copy visible pin numbers, paste above, then fine-tune with checkboxes below.")
            edited = st.data_editor(
                edit_df,
                column_config={
                    "Include": st.column_config.CheckboxColumn("Include", default=True),
                    "Renamed As": st.column_config.TextColumn("Renamed As"),
                    "Latitude": st.column_config.NumberColumn(format="%.6f"),
                    "Longitude": st.column_config.NumberColumn(format="%.6f"),
                    "#": st.column_config.NumberColumn("#"),
                    "File": st.column_config.TextColumn("File"),
                },
                disabled=["#", "File", "Renamed As", "Latitude", "Longitude"],
                hide_index=True,
                use_container_width=True,
                key="pin_editor",
            )
            # Persist for next rerun
            st.session_state["img_include"] = edited["Include"].tolist()

            # Build ZIP from checked rows with sequential renamed files
            n_zip = int(edited["Include"].sum())
            pad_zip = max(2, len(str(n_zip))) if n_zip else 2
            zip_buf = BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                rank = 0
                for i, (fp, _, __) in enumerate(coords):
                    if edited["Include"].iloc[i]:
                        rank += 1
                        new_name = f"{str(rank).zfill(pad_zip)}{os.path.splitext(fp)[1].lower()}"
                        zf.write(fp, arcname=new_name)
            zip_buf.seek(0)
            st.download_button(
                label=f"⬇️ Download ZIP ({n_zip} file{'s' if n_zip != 1 else ''})",
                data=zip_buf,
                file_name="renamed_pins.zip",
                mime="application/zip",
                key="download_zip_btn",
            )

            # Build KMZ from checked rows
            if n_zip > 0:
                kml_lines = [
                    '<?xml version="1.0" encoding="UTF-8"?>',
                    '<kml xmlns="http://www.opengis.net/kml/2.2">',
                    '<Document>',
                    '<name>Exported Pins</name>',
                ]
                rank = 0
                for i, (fp, lat, lon) in enumerate(coords):
                    if edited["Include"].iloc[i]:
                        rank += 1
                        new_name = f"{str(rank).zfill(pad_zip)}{os.path.splitext(fp)[1].lower()}"
                        img_path_in_kmz = f"files/{new_name}"
                        kml_lines += [
                            "<Placemark>",
                            f"  <name>{new_name}</name>",
                            "  <description><![CDATA[",
                            f"    <b>{new_name}</b><br>",
                            f"    Original: {os.path.basename(fp)}<br>",
                            f'    <img src="{img_path_in_kmz}" width="400">',
                            "  ]]></description>",
                            "  <Point>",
                            f"    <coordinates>{lon},{lat},0</coordinates>",
                            "  </Point>",
                            "</Placemark>",
                        ]
                kml_lines += ["</Document>", "</kml>"]
                kmz_buf = BytesIO()
                with zipfile.ZipFile(kmz_buf, "w", zipfile.ZIP_DEFLATED) as kz:
                    kz.writestr("doc.kml", "\n".join(kml_lines))
                    rank = 0
                    for i, (fp, _, __) in enumerate(coords):
                        if edited["Include"].iloc[i]:
                            rank += 1
                            new_name = f"{str(rank).zfill(pad_zip)}{os.path.splitext(fp)[1].lower()}"
                            kz.write(fp, arcname=f"files/{new_name}")
                kmz_buf.seek(0)
                st.download_button(
                    label=f"🗺️ Export KMZ ({n_zip} pin{'s' if n_zip != 1 else ''})",
                    data=kmz_buf,
                    file_name="exported_pins.kmz",
                    mime="application/vnd.google-earth.kmz",
                    key="download_kmz_btn",
                )

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

            pin_df = pd.DataFrame([
                {"#": i + 1, "Name": f["name"], "Latitude": round(f["lat"], 6), "Longitude": round(f["lon"], 6)}
                for i, f in enumerate(features)
            ])
            st.dataframe(
                pin_df,
                column_config={
                    "Latitude": st.column_config.NumberColumn(format="%.6f"),
                    "Longitude": st.column_config.NumberColumn(format="%.6f"),
                },
                hide_index=True,
                use_container_width=True,
            )
            st.caption("Toggle individual pins using the layer control (top-right of the map).")
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