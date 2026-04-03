import io
import base64
import os
import json

import streamlit as st
from PIL import Image, ImageDraw
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="AI Privacy Image Cleaner", page_icon="🛡️")

# ── Detection ─────────────────────────────────────────────────────────────────

def _get_secret(name: str) -> str:
    """Read from st.secrets if available, fall back to os.environ."""
    try:
        return str(st.secrets.get(name) or "")
    except Exception:
        return os.environ.get(name, "")

# ── Detection ─────────────────────────────────────────────────────────────────

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
        "Identify all cars, buildings, and people visible in this image. "
        "Return a JSON array. Each element must have: "
        "label (string), x, y, w, h (integer bounding box, top-left origin). "
        "For people ALSO include an 'outline' key: an array of [x,y] integer pairs "
        "forming a tight polygon around the person's body silhouette (10-20 points). "
        f"The image is {tw}×{th} pixels. "
        "Return ONLY the raw JSON array, no markdown, no explanation."
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_thumb}", "detail": "low"}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = response.choices[0].message.content.strip()
        boxes_thumb = json.loads(raw)
    except Exception:
        return []

    boxes = []
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

# ── Debug overlay ────────────────────────────────────────────────────────────

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

def build_mask(image: Image.Image, boxes: list[dict]) -> Image.Image:
    """
    Build an RGBA mask where detected regions are fully transparent
    (= inpaint here) and everything else is fully opaque (= keep).

    The OpenAI edit endpoint treats transparent pixels as the edit target.
    """
    # Start fully opaque (keep everything)
    mask = Image.new("RGBA", image.size, (0, 0, 0, 255))
    draw = ImageDraw.Draw(mask)
    for box in boxes:
        x, y, w, h = box["x"], box["y"], box["w"], box["h"]
        if "outline" in box and len(box["outline"]) >= 3:
            pts = [tuple(p) for p in box["outline"]]
            draw.polygon(pts, fill=(0, 0, 0, 0))
        else:
            draw.rectangle([x, y, x + w, y + h], fill=(0, 0, 0, 0))
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

    def _get_secret(name: str) -> str:
        """Read from st.secrets if available, fall back to os.environ."""
        try:
            return str(st.secrets.get(name) or "")
        except Exception:
            return os.environ.get(name, "")

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

# ── UI ────────────────────────────────────────────────────────────────────────

st.title("🛡️ AI Privacy Image Cleaner")
st.caption("Upload an image → auto-detect cars, people & buildings → inpaint with AI.")

uploaded_file = st.file_uploader("Upload image", type=["png", "jpg", "jpeg"])

if uploaded_file:
    image = Image.open(uploaded_file).convert("RGB")

    st.subheader("Original")
    st.image(image, use_container_width=True)

    quality = st.select_slider(
        "Output quality",
        options=["low", "medium", "high"],
        value="medium",
        help="low ≈ cheapest  |  medium = good balance  |  high = best quality",
    )

    debug = st.checkbox("🔎 Preview detections & mask before editing")

    if debug:
        with st.spinner("Running detection…"):
            dbg_boxes = detect_objects(image)
            dbg_mask  = build_mask(image, dbg_boxes)

        col1, col2 = st.columns(2)
        with col1:
            st.caption("Detected regions")
            st.image(draw_debug_overlay(image, dbg_boxes), use_container_width=True)
        with col2:
            st.caption("Mask (red = will be inpainted)")
            checkerboard = Image.new("RGB", dbg_mask.size, (180, 180, 180))
            checkerboard.paste(Image.new("RGB", dbg_mask.size, (220, 50, 50)), mask=dbg_mask.split()[3].point(lambda p: 255 - p))
            st.image(checkerboard, use_container_width=True)

    if st.button("🔍 Process image"):

        with st.spinner("Detecting objects…"):
            boxes = detect_objects(image)

        with st.spinner("Building mask…"):
            mask = build_mask(image, boxes)

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