import io
import base64
import os
import json
import tempfile
import urllib.request

import cv2
import numpy as np
import streamlit as st
from PIL import Image, ImageDraw, ImageOps
from openai import OpenAI

# ── YOLOv8n-ONNX model (downloaded on first use, cached in /tmp) ─────────────

_YOLO_MODEL_URL  = (
    "https://github.com/ultralytics/yolov5/releases/download/v7.0/yolov5n.onnx"
)
_YOLO_MODEL_PATH = os.path.join(tempfile.gettempdir(), "yolov5n.onnx")

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

    # YOLOv5 expects 640×640 RGB float NCHW, values 0–1
    # Cast to match whatever dtype the model was exported with
    resized = image.convert("RGB").resize((640, 640), Image.LANCZOS)
    inp = np.array(resized, dtype=np.float32) / 255.0
    inp = np.transpose(inp, (2, 0, 1))[np.newaxis]  # HWC → NCHW

    input_detail = session.get_inputs()[0]
    input_name = input_detail.name
    if input_detail.type == "tensor(float16)":
        inp = inp.astype(np.float16)
    raw = session.run(None, {input_name: inp})[0]  # shape (1, 25200, 85)

    # YOLOv5 output: (1, 25200, 85)  →  [cx, cy, w, h, obj_conf, class0…class79]
    preds = raw[0]  # (25200, 85)
    boxes = []
    sx, sy = iw / 640, ih / 640

    for row in preds:
        obj_conf = float(row[4])
        if obj_conf < conf_thresh:
            continue
        class_scores = row[5:]
        cls_id = int(np.argmax(class_scores))
        conf = obj_conf * float(class_scores[cls_id])
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
    Use GPT-4o-mini vision to detect cars, and people.
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

_EFFECTS = ["No effect", "Remove (inpaint)", "Gaussian blur", "Pixelate"]

_GROUP_DEFAULT_EFFECTS: dict[str, str] = {
    "People":         "Remove (inpaint)",
    "Vehicles":       "Pixelate",
    "Walls & fences": "No effect",
    "Buildings": "Gaussian blur",
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
                "Remove or blur all cars and people naturally. "
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


def apply_gaussian_blur(image: Image.Image, boxes: list[dict], sigma: int = 15) -> Image.Image:
    """Gaussian-blur the bounding-box regions of *boxes* in *image*."""
    result = np.array(image.convert("RGB"))
    for box in boxes:
        x, y, w, h = box["x"], box["y"], box["w"], box["h"]
        roi = result[y : y + h, x : x + w]
        if roi.size == 0:
            continue
        ksize = sigma * 2 + 1
        result[y : y + h, x : x + w] = cv2.GaussianBlur(roi, (ksize, ksize), 0)
    return Image.fromarray(result)


def apply_pixelate(image: Image.Image, boxes: list[dict], block_size: int = 15) -> Image.Image:
    """Pixelate (mosaic-censor) the bounding-box regions of *boxes* in *image*."""
    result = np.array(image.convert("RGB"))
    for box in boxes:
        x, y, w, h = box["x"], box["y"], box["w"], box["h"]
        roi = result[y : y + h, x : x + w]
        if roi.size == 0 or w == 0 or h == 0:
            continue
        small = cv2.resize(
            roi,
            (max(1, w // block_size), max(1, h // block_size)),
            interpolation=cv2.INTER_LINEAR,
        )
        result[y : y + h, x : x + w] = cv2.resize(
            small, (w, h), interpolation=cv2.INTER_NEAREST
        )
    return Image.fromarray(result)


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("🛡️ AI Privacy Image Cleaner")
st.caption("Upload images → auto-detect people & vehicles → inpaint locally or with AI.")

# ── Global settings (above file uploader so they apply to all files) ──────────
with st.expander("⚙️ Settings", expanded=False):
    detect_method = st.radio(
        "Detection method",
        options=[
            "Local — YOLOv5n ONNX (free, people & vehicles only)",
            "API — GPT-4o-mini (costs tokens, detects buildings too)",
        ],
        index=0,
        help=(
            "**Local**: no API key needed. ~7 MB ONNX model downloaded once to /tmp. "
            "Detects people, cars, trucks, motorcycles, bicycles.\n\n"
            "**API**: detects buildings, shops, walls etc. in addition to people/vehicles."
        ),
    )
    use_local_detect = detect_method.startswith("Local")
    if use_local_detect:
        st.caption("ℹ️ Building categories are not available with local detection.")

    inpaint_method = st.radio(
        "Inpainting method",
        options=["Local — OpenCV Telea (free, no API)", "OpenAI API (gpt-image-1)"],
        index=0,
        help=(
            "**Local OpenCV**: pixel-precise mask, free, instant — "
            "best for thin objects; large areas may look smeared.\n\n"
            "**OpenAI API**: high-quality generative fill, costs tokens, ≈soft mask edges."
        ),
    )
    use_local_inpaint = inpaint_method.startswith("Local")

    if not use_local_inpaint:
        quality = st.select_slider(
            "Output quality",
            options=["low", "medium", "high"],
            value="medium",
            help="low ≈ cheapest  |  medium = good balance  |  high = best quality",
        )
    else:
        radius = st.slider(
            "Inpaint radius (px)", min_value=3, max_value=40, value=15,
            help="Larger radius = smoother fill but slower and more bleed.",
        )

    st.divider()
    st.caption("**Default effect per object type**")
    group_effects: dict[str, str] = {}
    _gcols = st.columns(len(_CATEGORY_GROUPS))
    for _gc, grp in zip(_gcols, _CATEGORY_GROUPS):
        group_effects[grp] = _gc.selectbox(
            grp,
            options=_EFFECTS,
            index=_EFFECTS.index(_GROUP_DEFAULT_EFFECTS.get(grp, "No effect")),
            key=f"grp_effect_{grp}",
        )

    _bcol, _pcol = st.columns(2)
    blur_sigma  = _bcol.slider(
        "Blur strength", 5, 49, 15, step=2,
        help="Higher = stronger Gaussian blur. Applied to 'Gaussian blur' objects.",
    )
    pixel_block = _pcol.slider(
        "Pixelate block (px)", 5, 50, 15, step=5,
        help="Higher = larger mosaic squares. Applied to 'Pixelate' objects.",
    )

    st.divider()
    auto_detect = st.toggle(
        "Auto-detect objects on upload",
        value=False,
        help="When on, objects are detected automatically as soon as an image is uploaded (no button click needed). The detect button is still shown to manually re-run detection.",
    )
    auto_preview = st.toggle(
        "Auto-preview mask after detection",
        value=False,
        help="When on, the mask preview is shown automatically after objects are detected. The preview checkbox is still shown to toggle it manually.",
    )
    auto_process = st.toggle(
        "Auto-process images after detection",
        value=False,
        help="When on, inpainting runs automatically once objects are detected (using the active inpainting settings). A ZIP download button appears below all tabs when every image has been processed.",
    )
    clear_on_download = st.toggle(
        "Clear processed image from memory after download",
        value=True,
        help="Removes the processed result from session state once you download it, freeing memory. Re-process the image if you need it again. Recommended to keep enabled for app stability.",
    )

# ── File uploader ─────────────────────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "Upload image(s)", type=["png", "jpg", "jpeg"], accept_multiple_files=True
)

if not uploaded_files:
    st.info("Upload one or more images to get started.")
    st.stop()

tabs = st.tabs([f.name for f in uploaded_files])

for tab, uploaded_file in zip(tabs, uploaded_files):
    with tab:
        image = ImageOps.exif_transpose(Image.open(uploaded_file)).convert("RGB")

        # ── Image viewer (top of page — original until result is ready) ────────
        file_id = uploaded_file.name + str(uploaded_file.size)
        result_key = f"result_{file_id}"

        jump_key = f"jump_result_{file_id}"
        if result_key in st.session_state:
            _tab_result, _tab_orig = st.tabs(["✅ Result", "Original"])
            with _tab_result:
                st.image(st.session_state[result_key], use_container_width=True)
            with _tab_orig:
                st.image(image, use_container_width=True)
            # Clear the jump flag (no longer needed since Result is the first/default tab)
            st.session_state.pop(jump_key, None)
        else:
            st.subheader("Original")
            st.image(image, use_container_width=True)

        # ── Step 1: detect ────────────────────────────────────────────────────
        cache_key = f"boxes_{file_id}"

        # Auto-detect: run once when the result isn’t cached yet
        if auto_detect and cache_key not in st.session_state:
            with st.spinner("Auto-detecting objects…"):
                if use_local_detect:
                    st.session_state[cache_key] = detect_objects_local(image)
                else:
                    st.session_state[cache_key] = detect_objects(image)

        if st.button("🔍 Detect objects", key=f"detect_{file_id}"):
            with st.spinner("Detecting objects…"):
                if use_local_detect:
                    st.session_state[cache_key] = detect_objects_local(image)
                else:
                    st.session_state[cache_key] = detect_objects(image)

        boxes = st.session_state.get(cache_key)

        if boxes is None:
            st.info("Click **Detect objects** above.")
            continue

        if not boxes:
            st.warning("No objects detected in this image.")
            continue

        # ── Step 2: per-object effect selection ──────────────────────────────
        st.subheader("Detected objects — choose effect for each")
        st.caption(
            "Each object defaults to the group setting above. "
            "Override per-object by choosing from the dropdown."
        )

        from collections import defaultdict
        label_groups: dict[str, list[int]] = defaultdict(list)
        for i, box in enumerate(boxes):
            label_groups[box["label"]].append(i)

        # idx → resolved effect (only entries where effect != "No effect")
        object_effects: dict[int, str] = {}
        for label, indices in sorted(label_groups.items()):
            # Resolve which group this label belongs to
            grp_default = "No effect"
            for grp, cats in _CATEGORY_GROUPS.items():
                if any(c in label.lower() or label.lower() in c for c in cats):
                    grp_default = group_effects.get(grp, "No effect")
                    break

            with st.expander(
                f"{label} ({len(indices)} detected) — default: **{grp_default}**",
                expanded=False,
            ):
                cols = st.columns(min(len(indices), 3))
                for i, idx in enumerate(indices):
                    col = cols[i % len(cols)]
                    box = boxes[idx]
                    chosen = col.selectbox(
                        f"#{idx + 1}  ({box['x']}, {box['y']})",
                        options=["— group default —"] + _EFFECTS,
                        index=0,
                        key=f"eff_{file_id}_{idx}",
                    )
                    resolved = grp_default if chosen == "— group default —" else chosen
                    if resolved != "No effect":
                        object_effects[idx] = resolved

        active_boxes = [boxes[i] for i in sorted(object_effects)]

        # ── Step 3: preview ───────────────────────────────────────────────────
        show_preview = st.checkbox(
            "🔎 Preview mask for selected objects",
            value=auto_preview,
            key=f"prev_{file_id}",
        )
        if show_preview:
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

        # ── Step 4: process ───────────────────────────────────────────────────
        def _apply_all_effects(img, obj_effects):
            remove_boxes = [boxes[i] for i, e in obj_effects.items() if e == "Remove (inpaint)"]
            blur_boxes   = [boxes[i] for i, e in obj_effects.items() if e == "Gaussian blur"]
            pixel_boxes  = [boxes[i] for i, e in obj_effects.items() if e == "Pixelate"]
            result = img.copy()
            if blur_boxes:
                result = apply_gaussian_blur(result, blur_boxes, sigma=blur_sigma)
            if pixel_boxes:
                result = apply_pixelate(result, pixel_boxes, block_size=pixel_block)
            if remove_boxes:
                msk = build_mask(result, remove_boxes)
                if use_local_inpaint:
                    result = local_inpaint(result, msk, radius=radius)
                else:
                    result = edit_image(result, msk, quality=quality)
            return result

        if not object_effects:
            st.warning("No objects have an effect assigned — nothing to process.")
        else:
            # Auto-process: run once when result isn't cached yet
            if auto_process and result_key not in st.session_state:
                with st.spinner("Auto-processing…"):
                    try:
                        st.session_state[result_key] = _apply_all_effects(image, object_effects)
                        st.session_state[jump_key] = True
                    except RuntimeError as err:
                        st.error(str(err))

            if not auto_process and st.button("✨ Process image", key=f"process_{file_id}"):
                with st.spinner("Applying effects…"):
                    try:
                        st.session_state[result_key] = _apply_all_effects(image, object_effects)
                        st.session_state[jump_key] = True
                    except RuntimeError as err:
                        st.error(str(err))

            if result_key in st.session_state:
                result_img = st.session_state[result_key]

                def _clear_single_result(rk, jk):
                    st.session_state.pop(rk, None)
                    st.session_state.pop(jk, None)

                _single_dl_kwargs = {}
                if clear_on_download:
                    _single_dl_kwargs["on_click"] = _clear_single_result
                    _single_dl_kwargs["args"] = (result_key, jump_key)

                st.download_button(
                    label="⬇️ Download cleaned image",
                    data=_to_png_bytes(result_img),
                    file_name=f"cleaned_{uploaded_file.name}",
                    mime="image/png",
                    key=f"dl_{file_id}",
                    **_single_dl_kwargs,
                )
            elif auto_process:
                pass  # spinner already shown above; result will appear on next rerun
            else:
                st.info("Click **Process image** when ready.")

# ── ZIP download (shown when at least 2 results are ready) ───────────────────
if uploaded_files:
    import io as _io
    import zipfile

    result_items = []
    for uf in uploaded_files:
        fid = uf.name + str(uf.size)
        rk = f"result_{fid}"
        if rk in st.session_state:
            result_items.append((f"cleaned_{uf.name}", st.session_state[rk]))

    if len(result_items) >= 2:
        all_done = len(result_items) == len(uploaded_files)
        zip_label = (
            "⬇️ Download all cleaned images (.zip)"
            if all_done
            else f"⬇️ Download {len(result_items)}/{len(uploaded_files)} cleaned images (.zip)"
        )

        # Invalidate cached zip whenever the set of ready files changes
        current_zip_files = frozenset(name for name, _ in result_items)
        if st.session_state.get("_zip_files_set") != current_zip_files:
            st.session_state.pop("_zip_data", None)
            st.session_state.pop("_zip_files_set", None)

        if "_zip_data" not in st.session_state:
            st.divider()
            if st.button("🗜️ Prepare ZIP for download", help="Packages all processed images into a single .zip file. Only runs when clicked."):
                with st.spinner("Building ZIP…"):
                    zip_buf = _io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for fname, img in result_items:
                            zf.writestr(fname, _to_png_bytes(img))
                    zip_buf.seek(0)
                    st.session_state["_zip_data"] = zip_buf.getvalue()
                    st.session_state["_zip_files_set"] = current_zip_files
                st.rerun()
        else:
            st.divider()

            def _clear_all_results(fids):
                for fid in fids:
                    st.session_state.pop(f"result_{fid}", None)
                    st.session_state.pop(f"jump_result_{fid}", None)
                st.session_state.pop("_zip_data", None)
                st.session_state.pop("_zip_files_set", None)

            _zip_dl_kwargs = {}
            if clear_on_download:
                _all_fids = [uf.name + str(uf.size) for uf in uploaded_files]
                _zip_dl_kwargs["on_click"] = _clear_all_results
                _zip_dl_kwargs["args"] = (_all_fids,)

            st.download_button(
                label=zip_label,
                data=st.session_state["_zip_data"],
                file_name="cleaned_images.zip",
                mime="application/zip",
                **_zip_dl_kwargs,
            )