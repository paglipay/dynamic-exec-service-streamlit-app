import io
import base64
import os
import json
import tempfile
import urllib.request

import cv2
import numpy as np
import streamlit as st
from PIL import Image, ImageDraw
from openai import OpenAI

# ── YOLOv8n-ONNX model (downloaded on first use, cached in /tmp) ─────────────

_YOLO_MODEL_URL  = (
    "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.onnx"
)
_YOLO_MODEL_PATH = os.path.join(tempfile.gettempdir(), "yolov8n.onnx")

# COCO class indices we care about → our label names
_YOLO_CLASSES = {
    0:  "person",
    1:  "bicycle",
    2:  "car",
    3:  "motorcycle",
    5:  "bus",       # mapped to van
    7:  "truck",
}

# ── Config ────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="AI Privacy Image Cleaner", page_icon="🛡️")

# ── Detection ─────────────────────────────────────────────────────────────────

def _get_secret(name: str) -> str:
    """Read from st.secrets if available, fall back to os.environ."""
    try:
        return str(st.secrets.get(name) or "")
    except Exception:
        return os.environ.get(name, "")

@st.cache_resource(show_spinner="Loading local detection model…")
def _get_yolo_session():
    """Download YOLOv8n ONNX once, return a cached onnxruntime.InferenceSession."""
    import onnxruntime as ort
    if not os.path.exists(_YOLO_MODEL_PATH):
        urllib.request.urlretrieve(_YOLO_MODEL_URL, _YOLO_MODEL_PATH)
    return ort.InferenceSession(_YOLO_MODEL_PATH, providers=["CPUExecutionProvider"])


def detect_objects_local(image: Image.Image, conf_thresh: float = 0.4) -> list[dict]:
    """
    Detect people and vehicles locally with YOLOv8n ONNX.
    No API call. Does NOT detect buildings (not in COCO).
    Returns a list of dicts: {label, x, y, w, h}.
    """
    try:
        session = _get_yolo_session()
    except Exception as exc:
        st.warning(f"Local model load failed: {exc}")
        return []

    iw, ih = image.size

    # YOLOv8 expects 640×640 RGB float32 NCHW, values 0–1
    resized = image.convert("RGB").resize((640, 640), Image.LANCZOS)
    inp = np.array(resized, dtype=np.float32) / 255.0
    inp = np.transpose(inp, (2, 0, 1))[np.newaxis]  # HWC → NCHW

    input_name = session.get_inputs()[0].name
    raw = session.run(None, {input_name: inp})[0]  # shape (1, 84, 8400)

    # raw[0] rows: [cx, cy, w, h, class0_conf, class1_conf, …]
    preds = raw[0].T  # (8400, 84)
    boxes = []
    sx, sy = iw / 640, ih / 640

    for row in preds:
        class_scores = row[4:]
        cls_id = int(np.argmax(class_scores))
        conf = float(class_scores[cls_id])
        if conf < conf_thresh:
            continue
        label = _YOLO_CLASSES.get(cls_id)
        if label is None:
            continue
        cx, cy, bw, bh = row[:4]
        # YOLO coords are in 640-space; scale to original image
        x = max(0, int((cx - bw / 2) * sx))
        y = max(0, int((cy - bh / 2) * sy))
        w = min(iw - x, int(bw * sx))
        h = min(ih - y, int(bh * sy))
        if w > 0 and h > 0:
            boxes.append({"label": label, "x": x, "y": y, "w": w, "h": h})

    # Simple NMS: drop boxes with IoU > 0.5 against a higher-confidence box
    boxes.sort(key=lambda b: -(b["w"] * b["h"]))  # largest first as proxy
    kept, used = [], set()
    for i, b in enumerate(boxes):
        if i in used:
            continue
        kept.append(b)
        for j, other in enumerate(boxes[i + 1:], i + 1):
            if j in used:
                continue
            ix = max(b["x"], other["x"])
            iy = max(b["y"], other["y"])
            ix2 = min(b["x"] + b["w"], other["x"] + other["w"])
            iy2 = min(b["y"] + b["h"], other["y"] + other["h"])
            inter = max(0, ix2 - ix) * max(0, iy2 - iy)
            union = b["w"] * b["h"] + other["w"] * other["h"] - inter
            if union > 0 and inter / union > 0.5:
                used.add(j)
    return kept


# ── Detection (API) ───────────────────────────────────────────────────────────

def detect_objects(image: Image.Image) -> list[dict]:
    """
    Use GPT-4o-mini vision to detect cars, buildings, and people.
    Returns a list of dicts: {label, x, y, w, h} in pixel coordinates.
    Falls back to an empty list if detection fails.
    """
    api_key = _get_secret("OPENAI_API_KEY") or _get_secret("AI_API_KEY")
    if not api_key:
        return []

    # Downscale for the detection call to save tokens
    thumb = image.copy()
    thumb.thumbnail((512, 512), Image.LANCZOS)
    tw, th = thumb.size

    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=75)
    b64_thumb = base64.b64encode(buf.getvalue()).decode()

    prompt = (
        "Identify all objects in this image that fall into these categories: "
        "person, car, van, truck, motorcycle, bicycle, "
        "house, apartment building, shop/storefront, office building, industrial building, "
        "wall/fence, garage, shed. "
        "Return a JSON array. Each element must have: "
        "label (string, use the specific category name above), "
        "x, y, w, h (integer bounding box, top-left origin). "
        "For people ALSO include an 'outline' key: an array of [x,y] integer pairs "
        "forming a tight polygon around the person's body silhouette (10-20 points). "
        f"The image is {tw}×{th} pixels. "
        "Return ONLY the raw JSON array, no markdown, no explanation."
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_thumb}", "detail": "auto"}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if the model wraps the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        boxes_thumb = json.loads(raw)
    except json.JSONDecodeError as exc:
        st.warning(f"Detection failed: model returned invalid JSON — {exc}. Raw response: `{raw[:300]}`")
        return []
    except Exception as exc:
        st.warning(f"Detection failed: {exc}")
        return []

    boxes = []
    # Scale coordinates from thumbnail back to original image size
    iw, ih = image.size
    sx, sy = iw / tw, ih / th
    for b in boxes_thumb:
        try:
            entry = {
                "label": str(b["label"]),
                "x": max(0, int(b["x"] * sx)),
                "y": max(0, int(b["y"] * sy)),
                "w": min(iw, int(b["w"] * sx)),
                "h": min(ih, int(b["h"] * sy)),
            }
            if "outline" in b and isinstance(b["outline"], list):
                entry["outline"] = [
                    [max(0, int(p[0] * sx)), max(0, int(p[1] * sy))]
                    for p in b["outline"] if len(p) == 2
                ]
            boxes.append(entry)
        except (KeyError, TypeError, ValueError):
            continue
    return boxes

_CATEGORY_GROUPS = {
    "People":              ["person"],
    "Vehicles":            ["car", "van", "truck", "motorcycle", "bicycle"],
    "Private buildings":   ["house", "apartment building", "garage", "shed"],
    "Commercial buildings":["shop/storefront", "office building", "industrial building"],
    "Walls & fences":      ["wall/fence"],
}

def _label_matches(label: str, selected_groups: list[str]) -> bool:
    label_l = label.lower()
    for group in selected_groups:
        for cat in _CATEGORY_GROUPS.get(group, []):
            if cat in label_l or label_l in cat:
                return True
    return False


def draw_debug_overlay(image: Image.Image, boxes: list[dict]) -> Image.Image:
    """Draw labelled bounding boxes (and polygons for people) on a copy of *image*."""
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay, "RGBA")
    for box in boxes:
        x, y, w, h = box["x"], box["y"], box["w"], box["h"]
        if "outline" in box and len(box["outline"]) >= 3:
            pts = [tuple(p) for p in box["outline"]]
            draw.polygon(pts, outline=(255, 50, 50, 255))
            # also draw a thin bbox so the label anchor is clear
            draw.rectangle([x, y, x + w, y + h], outline=(255, 50, 50, 120), width=1)
        else:
            draw.rectangle([x, y, x + w, y + h], outline=(255, 50, 50, 255), width=3)
        draw.rectangle([x, y, x + len(box["label"]) * 7 + 6, y + 18], fill=(255, 50, 50, 200))
        draw.text((x + 3, y + 2), box["label"], fill=(255, 255, 255, 255))
    return overlay

# ── Mask ──────────────────────────────────────────────────────────────────────

def build_mask(image: Image.Image, boxes: list[dict], selected_groups: list[str] | None = None) -> Image.Image:
    """
    Build an RGBA mask where detected regions are fully transparent
    (= inpaint here) and everything else is fully opaque (= keep).

    The OpenAI edit endpoint treats transparent pixels as the edit target.
    """
    w, h = image.size

    # Draw a greyscale stencil: white = region to edit, black = keep.
    # ImageDraw reliably fills RGB/L images; we convert to RGBA alpha at the end.
    stencil = Image.new("L", (w, h), 0)   # all black = keep everything
    draw = ImageDraw.Draw(stencil)
    for box in boxes:
        if selected_groups is not None and not _label_matches(box["label"], selected_groups):
            continue
        bx, by, bw, bh = box["x"], box["y"], box["w"], box["h"]
        if "outline" in box and len(box["outline"]) >= 3:
            pts = [tuple(p) for p in box["outline"]]
            draw.polygon(pts, fill=255)
        else:
            draw.rectangle([bx, by, bx + bw, by + bh], fill=255)

    # Build RGBA mask: transparent where stencil is white, opaque where black.
    mask = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    # Invert stencil so white→0 (transparent) and black→255 (opaque)
    inv_stencil = stencil.point(lambda p: 255 - p)
    mask.putalpha(inv_stencil)
    return mask

# ── OpenAI edit ───────────────────────────────────────────────────────────────

def _to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

# Always use the smallest supported size — result is cropped+resized back anyway.
_API_SIZE = (1024, 1024)

def _letterbox(img: Image.Image, target_w: int, target_h: int) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """
    Fit *img* inside (target_w × target_h) with black padding.
    Returns (padded_image, crop_box) where crop_box is the region
    inside the padded image that contains the actual image content.
    """
    img.thumbnail((target_w, target_h), Image.LANCZOS)
    fw, fh = img.size
    ox = (target_w - fw) // 2
    oy = (target_h - fh) // 2
    padded = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 255))
    padded.paste(img, (ox, oy))
    return padded, (ox, oy, ox + fw, oy + fh)

def edit_image(image: Image.Image, mask: Image.Image, quality: str = "medium") -> Image.Image:
    """
    Send image + mask to gpt-image-1 for inpainting.
    quality: "low" | "medium" | "high"  (low ≈ 6× cheaper than high)
    Raises RuntimeError with a user-friendly message on failure.
    """
    orig_size = image.size

    # Letterbox both image and mask to the fixed API size
    api_w, api_h = _API_SIZE
    source_rgba, crop_box = _letterbox(image.convert("RGBA"), api_w, api_h)
    mask_lb, _ = _letterbox(mask.convert("RGBA"), api_w, api_h)

    api_key = _get_secret("OPENAI_API_KEY") or _get_secret("AI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OpenAI API key is not configured. Set OPENAI_API_KEY (or AI_API_KEY) "
            "in your Heroku config vars or .streamlit/secrets.toml."
        )
    client = OpenAI(api_key=api_key)
    try:
        result = client.images.edit(
            model="gpt-image-1",
            image=("image.png", _to_png_bytes(source_rgba), "image/png"),
            mask=("mask.png",  _to_png_bytes(mask_lb),      "image/png"),
            prompt=(
                "Remove or blur all cars, buildings, and people naturally. "
                "Keep pavement and environment consistent."
            ),
            quality=quality,
        )
    except Exception as exc:
        raise RuntimeError(f"OpenAI API error: {exc}") from exc

    b64 = result.data[0].b64_json
    if not b64:
        raise RuntimeError("API returned no image data.")

    # Crop the padding region and resize back to the original dimensions
    result_full = Image.open(io.BytesIO(base64.b64decode(b64)))
    result_cropped = result_full.crop(crop_box)
    return result_cropped.resize(orig_size, Image.LANCZOS)


def local_inpaint(image: Image.Image, mask: Image.Image, radius: int = 15) -> Image.Image:
    """
    CPU-only inpainting using the OpenCV Telea algorithm.
    Transparent pixels in *mask* are filled by propagating surrounding pixel values.
    Pixel-exact mask adherence with no API cost.
    Best for thin/small objects; large removed areas will look blurry/smeared.
    """
    img_rgb = np.array(image.convert("RGB"))
    # Alpha channel: 0 = transparent = inpaint here, 255 = keep
    alpha = np.array(mask.convert("RGBA"))[:, :, 3]
    cv_mask = np.where(alpha == 0, 255, 0).astype(np.uint8)
    result = cv2.inpaint(
        cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR),
        cv_mask,
        radius,
        cv2.INPAINT_TELEA,
    )
    return Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))

# ── UI ────────────────────────────────────────────────────────────────────────

st.title("🛡️ AI Privacy Image Cleaner")
st.caption("Upload an image → auto-detect cars, people & buildings → inpaint with AI.")

uploaded_file = st.file_uploader("Upload image", type=["png", "jpg", "jpeg"])

if uploaded_file:
    image = Image.open(uploaded_file).convert("RGB")

    st.subheader("Original")
    st.image(image, use_container_width=True)

    # ── Step 1: detect ────────────────────────────────────────────────────────
    file_id = uploaded_file.name + str(uploaded_file.size)
    if st.session_state.get("detect_file") != file_id:
        st.session_state.detected_boxes = None
        st.session_state.detect_file = file_id

    detect_method = st.radio(
        "Detection method",
        options=[
            "Local — YOLOv8n ONNX (free, people & vehicles only)",
            "API — GPT-4o-mini (costs tokens, detects buildings too)",
        ],
        help=(
            "**Local**: no API key needed. ~12 MB ONNX model downloaded once to /tmp. "
            "Detects people, cars, trucks, motorcycles, bicycles.  \n"
            "**API**: detects buildings, shops, walls etc. in addition to people/vehicles."
        ),
    )
    use_local_detect = detect_method.startswith("Local")
    if use_local_detect:
        st.caption("ℹ️ Building categories are not available with local detection.")

    if st.button("🔍 Detect objects"):
        with st.spinner("Detecting objects…"):
            if use_local_detect:
                st.session_state.detected_boxes = detect_objects_local(image)
            else:
                st.session_state.detected_boxes = detect_objects(image)

    boxes = st.session_state.get("detected_boxes")

    if boxes is None:
        st.info("Click **Detect objects** to find people, vehicles, and buildings.")
        st.stop()

    if not boxes:
        st.warning("No objects detected in this image.")
        st.stop()

    # ── Step 2: per-object include/exclude ────────────────────────────────────
    st.subheader("Detected objects — select which to remove")
    st.caption("Uncheck any object you want to keep unchanged.")

    from collections import defaultdict
    label_groups: dict[str, list[int]] = defaultdict(list)
    for i, box in enumerate(boxes):
        label_groups[box["label"]].append(i)

    active_indices: set[int] = set()
    for label, indices in sorted(label_groups.items()):
        default_on = _label_matches(label, ["People", "Vehicles"])
        with st.expander(f"{label} ({len(indices)} detected)", expanded=True):
            cols = st.columns(min(len(indices), 4))
            for col, idx in zip(cols * len(indices), indices):
                box = boxes[idx]
                checked = col.checkbox(
                    f"#{idx + 1}  ({box['x']}, {box['y']})",
                    value=default_on,
                    key=f"obj_{file_id}_{idx}",
                )
                if checked:
                    active_indices.add(idx)

    active_boxes = [boxes[i] for i in sorted(active_indices)]

    # ── Step 3: preview ───────────────────────────────────────────────────────
    if st.checkbox("🔎 Preview mask for selected objects"):
        preview_mask = build_mask(image, active_boxes)
        col1, col2 = st.columns(2)
        with col1:
            st.caption("All detections")
            st.image(draw_debug_overlay(image, boxes), use_container_width=True)
        with col2:
            st.caption("Mask (red = will be inpainted)")
            checker = Image.new("RGB", preview_mask.size, (180, 180, 180))
            checker.paste(
                Image.new("RGB", preview_mask.size, (220, 50, 50)),
                mask=preview_mask.split()[3].point(lambda p: 255 - p),
            )
            st.image(checker, use_container_width=True)

    # ── Step 4: process ───────────────────────────────────────────────────────
    method = st.radio(
        "Inpainting method",
        options=["OpenAI API (gpt-image-1)", "Local — OpenCV Telea (free, no API)"],
        help=(
            "**OpenAI API**: high-quality generative fill, costs tokens, ≈soft mask edges.\n\n"
            "**Local OpenCV**: pixel-precise mask, free, instant — "
            "best for thin objects; large areas may look smeared."
        ),
    )
    use_local = method.startswith("Local")

    if not use_local:
        quality = st.select_slider(
            "Output quality",
            options=["low", "medium", "high"],
            value="medium",
            help="low ≈ cheapest  |  medium = good balance  |  high = best quality",
        )
    else:
        radius = st.slider(
            "Inpaint radius (px)",
            min_value=3, max_value=40, value=15,
            help="Larger radius = smoother fill but slower and more bleed.",
        )

    if not active_boxes:
        st.warning("No objects selected — nothing to remove.")
    elif st.button("✨ Process image"):
        with st.spinner("Building mask…"):
            mask = build_mask(image, active_boxes)

        if use_local:
            with st.spinner("Running local inpainting…"):
                result_img = local_inpaint(image, mask, radius=radius)
        else:
            with st.spinner("Editing with AI…"):
                try:
                    result_img = edit_image(image, mask, quality=quality)
                except RuntimeError as err:
                    st.error(str(err))
                    st.stop()

        st.subheader("✅ Result")
        st.image(result_img, use_container_width=True)

        st.download_button(
            label="⬇️ Download cleaned image",
            data=_to_png_bytes(result_img),
            file_name="cleaned.png",
            mime="image/png",
        )