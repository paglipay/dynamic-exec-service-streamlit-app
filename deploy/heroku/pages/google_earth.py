import os
import re
import base64
import tempfile
import shutil
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
import copy
import math
from datetime import datetime

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
        img.close()
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f'<img src="data:image/jpeg;base64,{b64}" width="{width}">'
    except Exception:
        return "<i>Image preview unavailable</i>"


def image_fullsize_html(filepath, max_px=400):
    """Return an <img> tag with a base64 full-size image (capped at max_px), or an error string."""
    try:
        img = Image.open(filepath)
        img.thumbnail((max_px, max_px))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        w, h = img.size
        img.close()
        b64 = base64.b64encode(buf.getvalue()).decode()
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


# ── Visio XML helpers (Camera Grid tab) ──────────────────────────────────────

_VISIO_NS = "http://schemas.microsoft.com/office/visio/2012/main"
_RELS_NS  = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("",  _VISIO_NS)
ET.register_namespace("r", _RELS_NS)


def _vtag(name):
    return f"{{{_VISIO_NS}}}{name}"


def _strip_redundant_xmlns(xml_str):
    xml_str = (
        xml_str
        .replace(f'xmlns:ns0="{_VISIO_NS}"', f'xmlns="{_VISIO_NS}"')
        .replace(f'xmlns:ns1="{_RELS_NS}"',  f'xmlns:r="{_RELS_NS}"')
    )
    xml_str = re.sub(r'<(/?)ns0:', r'<\1', xml_str)
    xml_str = xml_str.replace(" ns0:", " ").replace(" ns1:", " r:")
    root_close = xml_str.index(">") + 1
    return xml_str[:root_close] + re.sub(
        r'\s+xmlns(?::\w+)?="[^"]*"', "", xml_str[root_close:]
    )


def _vget_cell(elem, name):
    for cell in elem.iter(_vtag("Cell")):
        if cell.get("N") == name:
            v = cell.get("V")
            if v is not None:
                try:
                    return float(v)
                except ValueError:
                    pass
    return None


def _vset_cell(elem, name, value):
    # Search the element's subtree for an existing Cell, but never recurse into
    # nested Shape/Shapes elements so we don't accidentally modify sub-shape geometry.
    def _find_set(node):
        for child in node:
            if child.tag == _vtag("Cell") and child.get("N") == name:
                child.set("V", str(value))
                child.attrib.pop("F", None)
                return True
            if child.tag not in (_vtag("Shape"), _vtag("Shapes")):
                if _find_set(child):
                    return True
        return False

    if not _find_set(elem):
        c = ET.SubElement(elem, _vtag("Cell"))
        c.set("N", name)
        c.set("V", str(value))


def _vset_prop(elem, prop_name, value):
    sec = None
    for s in elem.findall(_vtag("Section")):
        if s.get("N") == "Property":
            sec = s
            break
    if sec is None:
        sec = ET.SubElement(elem, _vtag("Section"))
        sec.set("N", "Property")
    row = None
    for r in sec.findall(_vtag("Row")):
        if r.get("N") == prop_name:
            row = r
            break
    if row is None:
        row = ET.SubElement(sec, _vtag("Row"))
        row.set("N", prop_name)
    for cell in row.findall(_vtag("Cell")):
        if cell.get("N") == "Value":
            cell.set("V", str(value))
            cell.attrib.pop("F", None)
            return
    c = ET.SubElement(row, _vtag("Cell"))
    c.set("N", "Value")
    c.set("V", str(value))


def _vset_label(group_elem, cam_id):
    sub_container = group_elem.find(_vtag("Shapes"))
    if sub_container is None:
        return
    for sub in list(sub_container):
        sub_name = sub.get("NameU") or sub.get("Name") or ""
        if sub_name != "label":
            continue
        for sec in list(sub.findall(_vtag("Section"))):
            if sec.get("N") == "Field":
                sub.remove(sec)
        text_elem = sub.find(_vtag("Text"))
        if text_elem is not None:
            sub.remove(text_elem)
        text_elem = ET.SubElement(sub, _vtag("Text"))
        text_elem.text = str(cam_id)


def _vis_is_camera(shape_elem):
    if shape_elem.get("Type") != "Group":
        return False
    for sec in shape_elem.findall(_vtag("Section")):
        if sec.get("N") != "Property":
            continue
        for row in sec.findall(_vtag("Row")):
            if row.get("N") == "CamID":
                return True
    return False


def _vmax_shape_id(tree):
    max_id = 0
    for shape in tree.iter(_vtag("Shape")):
        try:
            sid = int(shape.get("ID", 0))
            if sid > max_id:
                max_id = sid
        except ValueError:
            pass
    return max_id


def _vreassign_sub_ids(elem, next_id):
    sub_container = elem.find(_vtag("Shapes"))
    if sub_container is None:
        return next_id
    for sub in sub_container:
        if sub.tag == _vtag("Shape"):
            sub.set("ID", str(next_id))
            next_id += 1
            next_id = _vreassign_sub_ids(sub, next_id)
    return next_id


def _vbuild_grid(tree, n_cameras, source_shape_id=61, cols=4, x_spacing=1000.0, y_spacing=1000.0):
    """Duplicate source_shape_id into a grid of exactly n_cameras shapes (ceil(n/cols) rows × cols cols)."""
    shapes_container = tree.find(_vtag("Shapes"))
    if shapes_container is None:
        raise RuntimeError("No <Shapes> container found on this page.")
    source_elem = None
    for s in shapes_container:
        if s.get("ID") == str(source_shape_id):
            source_elem = s
            break
    if source_elem is None:
        raise ValueError(
            f"Shape ID {source_shape_id} not found in the template. "
            "Check the Source Shape ID in Advanced Options."
        )
    origin_x = _vget_cell(source_elem, "PinX") or 0.0
    origin_y = _vget_cell(source_elem, "PinY") or 0.0
    width  = _vget_cell(source_elem, "Width")
    height = _vget_cell(source_elem, "Height")
    step_x = width  if (x_spacing == 0.0 and width)  else x_spacing
    step_y = height if (y_spacing == 0.0 and height) else y_spacing
    is_camera = _vis_is_camera(source_elem)
    rows = math.ceil(n_cameras / cols)
    cam_counter = 1
    next_id = _vmax_shape_id(tree) + 1
    placed = 0
    for row in range(rows):
        for col in range(cols):
            if placed >= n_cameras:
                break
            new_elem = copy.deepcopy(source_elem)
            new_elem.set("ID",    str(next_id))
            new_elem.set("Name",  f"GridCopy.{next_id}")
            new_elem.set("NameU", f"GridCopy.{next_id}")
            next_id += 1
            next_id = _vreassign_sub_ids(new_elem, next_id)
            pin_x = origin_x + col * step_x
            pin_y = origin_y - row * step_y
            _vset_cell(new_elem, "PinX", pin_x)
            _vset_cell(new_elem, "PinY", pin_y)
            if is_camera:
                _vset_prop(new_elem, "CamID", cam_counter)
                _vset_label(new_elem, cam_counter)
                cam_counter += 1
            shapes_container.append(new_elem)
            placed += 1


def _vapply_replacements(tree, replacements):
    """Replace tokens in every <Text> element on the Visio page."""
    changed = 0
    for text_elem in tree.iter(_vtag("Text")):
        for node in text_elem.iter():
            for attr in ("text", "tail"):
                original = getattr(node, attr)
                if not original:
                    continue
                updated = original
                for old, new in replacements:
                    updated = updated.replace(old, new)
                if updated != original:
                    setattr(node, attr, updated)
                    changed += 1
    return changed


@st.cache_data(ttl=300, show_spinner=False)
def _load_r1_schools():
    """Load all records from the r1_data MongoDB collection."""
    mongo_uri = os.environ.get("MONGODB_URI", "")
    if not mongo_uri:
        return []
    try:
        from pymongo import MongoClient
        from urllib.parse import urlparse, unquote
        parsed  = urlparse(mongo_uri)
        db_name = unquote((parsed.path or "").lstrip("/")).split("?")[0].strip() or "app_data"
        client  = MongoClient(mongo_uri, serverSelectionTimeoutMS=4000)
        cursor  = client[db_name]["r1_data"].find(
            {},
            {"_id": 0, "School Name": 1, "Site": 1, "Loc Code": 1,
             "Address": 1, "City": 1, "Contractor": 1},
        ).sort("School Name", 1)
        return [dict(doc) for doc in cursor]
    except Exception:
        return []


# ── Satellite tile capture (for Visio background) ─────────────────────────────

_ARCGIS_TILE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
_MAX_TILES   = 144   # 12×12 safety cap
_GPS_ZOOM    = 20    # zoom level used for both tile capture and GPS→Visio mapping


def _latlon_to_tile(lat, lon, zoom):
    """Return tile (x, y) for a lat/lon at the given zoom level."""
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _latlon_to_tile_f(lat, lon, zoom):
    """Float-precision tile coordinates (Mercator) — used for sub-tile position mapping."""
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def _geocode_address(address, city=""):
    """Geocode an address using Nominatim. Returns (lat, lon) or (None, None)."""
    query = f"{address}, {city}".strip(", ") if city else address
    if not query:
        return None, None
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "visio-camera-layout-tool/1.0"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass
    return None, None


def _fetch_satellite_image(coords, zoom=19, padding_tiles=2):
    """
    Stitch ArcGIS World Imagery tiles covering the bounding box of coords.
    coords: list of (filepath, lat, lon)
    Returns a PNG bytes object, or None if coords is empty or tile count exceeds _MAX_TILES.
    """
    lats = [c[1] for c in coords]
    lons = [c[2] for c in coords]
    if not lats:
        return None

    # Tile range for the bounding box (NW → SE)
    x_min, y_min = _latlon_to_tile(max(lats), min(lons), zoom)
    x_max, y_max = _latlon_to_tile(min(lats), max(lons), zoom)

    # Add padding
    x_min = max(0, x_min - padding_tiles)
    y_min = max(0, y_min - padding_tiles)
    x_max = x_max + padding_tiles
    y_max = y_max + padding_tiles

    tile_w = x_max - x_min + 1
    tile_h = y_max - y_min + 1
    if tile_w * tile_h > _MAX_TILES:
        return None  # too many tiles — skip silently

    canvas = Image.new("RGB", (tile_w * 256, tile_h * 256))
    for tx in range(x_min, x_max + 1):
        for ty in range(y_min, y_max + 1):
            url = _ARCGIS_TILE.format(z=zoom, y=ty, x=tx)
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    tile_img = Image.open(BytesIO(resp.content)).convert("RGB")
                    canvas.paste(tile_img, ((tx - x_min) * 256, (ty - y_min) * 256))
                    tile_img.close()
            except Exception:
                pass  # leave that tile black, continue

    buf = BytesIO()
    canvas.save(buf, format="PNG")
    canvas.close()
    return buf.getvalue()


def _get_page_dimensions(tree):
    """Read PageWidth and PageHeight (inches) from the Visio page XML."""
    page_sheet = tree.find(_vtag("PageSheet"))
    w = h = None
    if page_sheet is not None:
        for cell in page_sheet.iter(_vtag("Cell")):
            n = cell.get("N")
            try:
                if n == "PageWidth":
                    w = float(cell.get("V", 0))
                elif n == "PageHeight":
                    h = float(cell.get("V", 0))
            except (TypeError, ValueError):
                pass
    return w or 11.0, h or 8.5


def _vplace_cameras_by_gps(tree, coords, source_shape_id=61, margin_frac=0.08):
    """
    Place one camera shape per (filepath, lat, lon) entry in coords, positioned
    on the Visio page using Mercator-correct GPS-to-page mapping.

    The bounding box of the coords (plus padding) determines the mapping so the
    layout matches the satellite image captured by _fetch_satellite_image.

    margin_frac: fraction of page dimension used as margin on each side (default 8%).
    """
    shapes_container = tree.find(_vtag("Shapes"))
    if shapes_container is None:
        raise RuntimeError("No <Shapes> container found on this page.")

    source_elem = None
    for s in shapes_container:
        if s.get("ID") == str(source_shape_id):
            source_elem = s
            break
    if source_elem is None:
        raise ValueError(
            f"Shape ID {source_shape_id} not found in the template. "
            "Check the Source Shape ID in Advanced Options."
        )

    page_w, page_h = _get_page_dimensions(tree)

    # Calibrate: if the source shape's PinX is far outside normal inch-based page bounds,
    # the template likely uses a scaled coordinate system — derive the scale factor so
    # GPS positions map into the same unit space.
    src_pin_x = _vget_cell(source_elem, "PinX") or 0.0
    src_pin_y = _vget_cell(source_elem, "PinY") or 0.0
    scale = 1.0
    if page_w > 0 and src_pin_x > page_w * 2:
        # Source shape is well outside inch-based page → compute scale from its position
        scale = src_pin_x / (page_w / 2.0)  # assume source is near page center

    margin_x = page_w * margin_frac * scale
    margin_y = page_h * margin_frac * scale
    usable_w = page_w * scale - 2 * margin_x
    usable_h = page_h * scale - 2 * margin_y

    # Compute Mercator tile coordinates for every pin (float precision)
    tile_coords = [_latlon_to_tile_f(lat, lon, _GPS_ZOOM) for _, lat, lon in coords]
    tx_all = [tc[0] for tc in tile_coords]
    ty_all = [tc[1] for tc in tile_coords]

    tx_min, tx_max = min(tx_all), max(tx_all)
    ty_min, ty_max = min(ty_all), max(ty_all)

    # Add the same 2-tile padding used when capturing the satellite image
    padding = 2.0
    tx_min -= padding
    tx_max += padding
    ty_min -= padding
    ty_max += padding

    span_x = tx_max - tx_min or 1.0
    span_y = ty_max - ty_min or 1.0

    is_camera = _vis_is_camera(source_elem)
    next_id     = _vmax_shape_id(tree) + 1
    cam_counter = 1

    for idx, (tc, (_, lat, lon)) in enumerate(zip(tile_coords, coords)):
        new_elem = copy.deepcopy(source_elem)
        new_elem.set("ID",    str(next_id))
        new_elem.set("Name",  f"GpsCam.{next_id}")
        new_elem.set("NameU", f"GpsCam.{next_id}")
        next_id += 1
        next_id = _vreassign_sub_ids(new_elem, next_id)

        # frac_x: 0=west edge, 1=east edge
        # frac_y: 0=north edge, 1=south edge (tile Y increases southward)
        frac_x = (tc[0] - tx_min) / span_x
        frac_y = (tc[1] - ty_min) / span_y

        # Visio origin is bottom-left; north = top = higher Y
        pin_x = margin_x + frac_x * usable_w
        pin_y = margin_y + (1.0 - frac_y) * usable_h

        _vset_cell(new_elem, "PinX", pin_x)
        _vset_cell(new_elem, "PinY", pin_y)

        if is_camera:
            _vset_prop(new_elem, "CamID", cam_counter)
            _vset_label(new_elem, cam_counter)
            cam_counter += 1

        shapes_container.append(new_elem)


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

tab1, tab2, tab3 = st.tabs(["🖼️ Image Folder (EXIF GPS)", "🗺️ KML Upload", "📐 Visio Camera Grid"])

# ── Tab 1: image folder / zip upload ─────────────────────────────────────────
with tab1:
    st.markdown("Upload a **ZIP file** containing images, or enter a local folder path.")

    uploaded_zip = st.file_uploader(
        "Upload ZIP of images", type=["zip"], key=f"zip_uploader_{st.session_state.get('zip_upload_gen', 0)}",
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
            # ZIP bytes no longer needed — reset uploader widget to free memory
            if uploaded_zip is not None:
                st.session_state["zip_upload_gen"] = st.session_state.get("zip_upload_gen", 0) + 1
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

            # ── Trim unselected pins from memory ─────────────────────────────
            n_zip = int(edited["Include"].sum())
            n_unchecked = len(coords) - n_zip
            if n_unchecked > 0 and n_zip > 0:
                if st.button(
                    f"✂️ Trim to selection ({n_zip} kept, {n_unchecked} dropped)",
                    key="trim_pins_btn",
                    help="Permanently removes unselected pins from memory to free RAM. Cannot be undone without re-scanning.",
                ):
                    trimmed = [c for c, inc in zip(coords, st.session_state["img_include"]) if inc]
                    st.session_state["img_coords"]    = trimmed
                    st.session_state["img_include"]   = [True] * len(trimmed)
                    st.session_state["img_coord_key"] = tuple(os.path.basename(fp) for fp, _, __ in trimmed)
                    st.session_state.pop("pin_editor", None)
                    st.session_state.pop("pin_list_input", None)
                    st.rerun()
            # ─────────────────────────────────────────────────────────────────

            # Build ZIP from checked rows with sequential renamed files
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

# ── Tab 3: Visio Camera Grid ──────────────────────────────────────────────────
with tab3:
    st.markdown("Generate a **Visio Camera Grid** `.vsdx` for the cameras selected in the Image Folder tab.")

    # Camera count from pin selection
    include_flags = st.session_state.get("img_include", [])
    n_selected = sum(1 for v in include_flags if v)

    if not include_flags:
        st.info("Scan images in the **Image Folder** tab and select pins to pre-fill the camera count.")

    # Keep the widget in sync with the current selection so stale values don't silently override
    if n_selected > 0:
        st.session_state["visio_cam_count"] = n_selected

    camera_count_input = st.number_input(
        "Camera count",
        value=max(1, n_selected),
        min_value=1,
        step=1,
        key="visio_cam_count",
        help="Defaults to the number of pins selected in Tab 1. Edit to override.",
    )
    if n_selected > 0:
        st.caption(
            f"\u2139\ufe0f {n_selected} pin(s) selected in Tab 1. "
            f"GPS placement will be used \u2014 grid settings are ignored."
        )

    # School selector
    st.divider()
    schools = _load_r1_schools()
    if not schools:
        st.warning("No schools loaded. Ensure `MONGODB_URI` is set and the `r1_data` collection is accessible.")

    school_options = [
        f"{s.get('School Name') or s.get('Site') or 'Unknown'} ({s.get('Loc Code', '')})"
        for s in schools
    ]
    selected_label = st.selectbox(
        "School",
        ["— select —"] + school_options,
        key="visio_school_select",
    )
    selected_school = None
    if selected_label != "— select —" and schools:
        idx = school_options.index(selected_label)
        selected_school = schools[idx]

    if selected_school:
        with st.expander("School details"):
            st.json({k: str(v) for k, v in selected_school.items()})

    # Template upload
    st.divider()
    template_file = st.file_uploader(
        "Upload template .vsdx",
        type=["vsdx"],
        key="visio_template_upload",
        help="The camera group shape will be duplicated to fill the grid.",
    )

    # Advanced options
    with st.expander("Advanced options"):
        source_shape_id = st.number_input(
            "Source shape ID (camera group to duplicate)",
            value=61,
            min_value=1,
            step=1,
            key="visio_source_id",
            help="Shape ID of the camera group in the template. Default is 61 for Template - Camera Layout - v1.3.vsdx.",
        )
        x_spacing = st.number_input("X spacing (Visio units)", value=1000.0, step=100.0, key="visio_xspacing")
        y_spacing = st.number_input("Y spacing (Visio units)", value=1000.0, step=100.0, key="visio_yspacing")

    # Generate
    st.divider()
    can_generate = (
        int(camera_count_input) > 0
        and selected_school is not None
        and template_file is not None
    )
    if st.button("📐 Generate Visio", disabled=not can_generate, key="visio_generate_btn"):
        _gen_error = None
        _gen_bytes = None
        _gen_name  = None
        st.session_state.pop("visio_output", None)
        try:
            with st.spinner("Building Visio file\u2026"):
                vsdx_bytes = template_file.read()

                _contents = {}
                _info_list = []
                with zipfile.ZipFile(BytesIO(vsdx_bytes), "r") as _zf:
                    _contents  = {n: _zf.read(n) for n in _zf.namelist()}
                    _info_list = _zf.infolist()

                _PAGE_KEY = "visio/pages/page1.xml"
                if _PAGE_KEY not in _contents:
                    _avail = [k for k in _contents if k.startswith("visio/pages/page")]
                    raise FileNotFoundError(f"Page 1 not found in VSDX. Available: {_avail}")

                _tree = ET.fromstring(_contents[_PAGE_KEY])

                # ── Resolve selected coords early — used for both placement and satellite image
                _all_coords  = st.session_state.get("img_coords", [])
                _inc_flags   = st.session_state.get("img_include", [])
                _sel_coords  = (
                    [c for c, inc in zip(_all_coords, _inc_flags) if inc]
                    if _all_coords and any(_inc_flags)
                    else _all_coords
                )

                if _sel_coords:
                    st.write(f"📍 Placing **{len(_sel_coords)}** camera(s) from GPS coordinates.")
                    # GPS-based placement — one camera per selected pin
                    _vplace_cameras_by_gps(
                        _tree,
                        coords=_sel_coords,
                        source_shape_id=int(source_shape_id),
                    )
                else:
                    st.write(f"📐 No GPS pins selected — using uniform grid of **{int(camera_count_input)}** camera(s).")
                    # No GPS data — fall back to uniform grid
                    _vbuild_grid(
                        _tree,
                        n_cameras=int(camera_count_input),
                        source_shape_id=int(source_shape_id),
                        cols=4,
                        x_spacing=float(x_spacing),
                        y_spacing=float(y_spacing),
                    )

                _school_name = str(selected_school.get("School Name") or selected_school.get("Site") or "")
                _loc_raw     = selected_school.get("Loc Code", "")
                _loc_code    = (
                    str(int(_loc_raw))
                    if isinstance(_loc_raw, float) and _loc_raw == int(_loc_raw)
                    else str(_loc_raw).strip()
                )
                _address    = str(selected_school.get("Address") or "").strip()
                _contractor = str(selected_school.get("Contractor") or "").strip()
                _today      = datetime.now().strftime("%m/%d/%y")
                _replacements = [
                    ("<SCHOOL_NAME>",   _school_name),
                    ("<LOCATION_CODE>", _loc_code),
                    ("<ADDRESS>",       _address),
                    ("<VENDOR>",        _contractor),
                    ("<DATE>",          _today),
                ]
                _vapply_replacements(_tree, _replacements)

                # ── Satellite background image ────────────────────────────────
                if _sel_coords:
                    _sat_png = _fetch_satellite_image(_sel_coords, zoom=_GPS_ZOOM, padding_tiles=2)
                    if _sat_png and "visio/media/image3.png" in _contents:
                        _contents["visio/media/image3.png"] = _sat_png
                elif selected_school:
                    _geo_lat, _geo_lon = _geocode_address(
                        str(selected_school.get("Address") or "").strip(),
                        str(selected_school.get("City") or "").strip(),
                    )
                    if _geo_lat is not None:
                        _sat_png = _fetch_satellite_image(
                            [("school", _geo_lat, _geo_lon)],
                            zoom=_GPS_ZOOM,
                            padding_tiles=4,
                        )
                        if _sat_png and "visio/media/image3.png" in _contents:
                            _contents["visio/media/image3.png"] = _sat_png
                # ─────────────────────────────────────────────────────────────

                _xml_body = ET.tostring(_tree, encoding="unicode")
                _xml_body = _strip_redundant_xmlns(_xml_body)
                _contents[_PAGE_KEY] = (
                    "<?xml version='1.0' encoding='utf-8' ?>\r\n" + _xml_body
                ).encode("utf-8")

                _out_buf = BytesIO()
                _info_by_name = {i.filename: i for i in _info_list}
                with zipfile.ZipFile(_out_buf, "w", zipfile.ZIP_DEFLATED) as _zout:
                    for _fname, _fdata in _contents.items():
                        _zinfo = _info_by_name.get(_fname)
                        _zout.writestr(_zinfo if _zinfo else _fname, _fdata)
                del _contents  # free template bytes before storing output

                _safe     = re.sub(r'[<>:"/\\|?*]', "_", _school_name).strip() or "output"
                _gen_name  = f"{_safe} - Camera Layout.vsdx"
                _gen_bytes = _out_buf.getvalue()

        except Exception as _exc:
            _gen_error = str(_exc)

        if _gen_error:
            st.error(f"Error generating Visio file: {_gen_error}")
        else:
            st.session_state["visio_output"]   = _gen_bytes
            st.session_state["visio_filename"] = _gen_name
            st.success(f"Generated **{_gen_name}** with {int(camera_count_input)} camera(s).")

    if st.session_state.get("visio_output"):
        st.download_button(
            label="\u2b07\ufe0f Download .vsdx",
            data=st.session_state["visio_output"],
            file_name=st.session_state.get("visio_filename", "output.vsdx"),
            mime="application/vnd.ms-visio.drawing",
            key="visio_download_btn",
        )