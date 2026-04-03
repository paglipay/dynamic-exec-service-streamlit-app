import io
import base64
import os

import streamlit as st
from PIL import Image, ImageDraw
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="AI Privacy Image Cleaner", page_icon="🛡️")

# ── Detection ─────────────────────────────────────────────────────────────────

def detect_objects(image: Image.Image) -> list[dict]:
    """
    Placeholder detector — returns hardcoded bounding boxes.
    TODO: replace with YOLO / Detectron2 inference.

    Returns a list of dicts: {label, x, y, w, h}
    """
    w, h = image.size
    return [
        {"label": "building", "x": int(w * 0.6), "y": 0,            "w": int(w * 0.4), "h": int(h * 0.4)},
        {"label": "car",      "x": int(w * 0.5), "y": int(h * 0.4), "w": int(w * 0.5), "h": int(h * 0.6)},
    ]

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
        # Transparent = "please edit this region"
        draw.rectangle([x, y, x + w, y + h], fill=(0, 0, 0, 0))
    return mask

# ── OpenAI edit ───────────────────────────────────────────────────────────────

def _to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

# OpenAI edit only supports these output sizes; pick the best fit for the input.
_API_SIZES = [(1024, 1024), (1536, 1024), (1024, 1536)]

def _best_api_size(w: int, h: int) -> tuple[int, int]:
    """Return the API size whose aspect ratio is closest to w:h."""
    input_ratio = w / h
    return min(_API_SIZES, key=lambda s: abs(s[0] / s[1] - input_ratio))

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

def edit_image(image: Image.Image, mask: Image.Image) -> Image.Image:
    """
    Send image + mask to gpt-image-1 for inpainting.
    Raises RuntimeError with a user-friendly message on failure.
    """
    orig_size = image.size

    # Letterbox both image and mask to the closest supported API size
    api_w, api_h = _best_api_size(*orig_size)
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

    if st.button("🔍 Process image"):

        with st.spinner("Detecting objects…"):
            boxes = detect_objects(image)

        with st.spinner("Building mask…"):
            mask = build_mask(image, boxes)

        st.subheader("Mask (transparent = edited region)")
        # Show mask on a grey background so transparent areas are visible
        checkerboard = Image.new("RGB", mask.size, (180, 180, 180))
        checkerboard.paste(Image.new("RGB", mask.size, (255, 255, 255)), mask=mask.split()[3])
        st.image(checkerboard, use_container_width=True)

        with st.spinner("Editing with AI…"):
            try:
                result_img = edit_image(image, mask)
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