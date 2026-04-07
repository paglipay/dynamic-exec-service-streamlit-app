import hashlib
import io
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime

import streamlit as st
from _auth_guard import require_authentication

st.set_page_config(page_title="Camera Media Renamer")
require_authentication("Camera Media Renamer")
st.title("Camera Media Renamer")
st.caption(
    "Upload video and image files. Videos act as markers to group and number images — "
    "only images are included in the ZIP. Naming scheme: "
    "`01_INSTALL.jpg`, `01A.jpg`, `01B.jpg`, `02_INSTALL.jpg`, …"
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIDEO_EXTS = {'.mov', '.mp4', '.avi', '.mkv', '.wmv', '.flv', '.mpeg', '.mpg'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
ACCEPTED_TYPES = [
    "image/jpeg", "image/png", "image/bmp", "image/gif", "image/tiff", "image/webp",
    "video/quicktime", "video/mp4", "video/x-msvideo", "video/x-matroska",
    "video/x-ms-wmv", "video/x-flv", "video/mpeg",
]

# ---------------------------------------------------------------------------
# Date-extraction helpers
# ---------------------------------------------------------------------------


def _image_date_from_bytes(data: bytes) -> float | None:
    try:
        from PIL import Image, ExifTags
        with Image.open(io.BytesIO(data)) as img:
            exif_data = img._getexif()
            if not exif_data:
                return None
            tag_map = {v: k for k, v in ExifTags.TAGS.items()}
            dto_tag = tag_map.get("DateTimeOriginal")
            if dto_tag and dto_tag in exif_data:
                return datetime.strptime(exif_data[dto_tag], "%Y:%m:%d %H:%M:%S").timestamp()
    except Exception:
        pass
    return None


def _video_date_from_bytes(data: bytes, suffix: str) -> float | None:
    import os
    tmp_path = None
    try:
        from hachoir.parser import createParser
        from hachoir.metadata import extractMetadata
        # Use SpooledTemporaryFile so videos < 10 MB stay in RAM; larger spill to disk
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        parser = createParser(tmp_path)
        if parser:
            with parser:
                metadata = extractMetadata(parser)
            if metadata:
                for field in ("creation_date", "date_time_original"):
                    val = metadata.get(field)
                    if val:
                        if hasattr(val, "timestamp"):
                            return val.timestamp()
                        if isinstance(val, str):
                            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S"):
                                try:
                                    return datetime.strptime(val, fmt).timestamp()
                                except ValueError:
                                    pass
    except Exception:
        pass
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    return None


def _taken_time(data: bytes, ext: str, upload_index: int) -> float:
    """Best-effort date taken; falls back to upload order (index) so sort is stable."""
    if ext in IMAGE_EXTS:
        t = _image_date_from_bytes(data)
    elif ext in VIDEO_EXTS:
        t = _video_date_from_bytes(data, ext)
    else:
        t = None
    return t if t is not None else float(upload_index)


# ---------------------------------------------------------------------------
# Image resize helper
# ---------------------------------------------------------------------------


def _resize_image_bytes(data: bytes, max_px: int = 1920) -> bytes:
    """Resize an image so its longest side is at most *max_px* pixels.
    Returns the original bytes unchanged if already within the limit or on error.
    """
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
            if max(w, h) <= max_px:
                return data
            scale = max_px / max(w, h)
            new_size = (int(w * scale), int(h * scale))
            # Preserve EXIF so date extraction still works after resize
            exif = img.info.get("exif", b"")
            resized = img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            fmt = img.format or "JPEG"
            save_kwargs = {"format": fmt}
            if exif:
                save_kwargs["exif"] = exif
            resized.save(buf, **save_kwargs)
            return buf.getvalue()
    except Exception:
        return data


def _build_plan(uploaded_files, use_upload_order: bool = False):
    """
    Returns list of (original_name, new_name, bytes) for every file that gets
    a new name.  Images are always resized to ≤ 1920 px to reduce memory usage.
    """
    entries = []
    for i, uf in enumerate(uploaded_files):
        ext = Path(uf.name).suffix.lower()
        if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
            continue
        data = uf.getvalue()
        if ext in IMAGE_EXTS:
            data = _resize_image_bytes(data)
        sort_key = float(i) if use_upload_order else _taken_time(data, ext, i)
        entries.append((uf.name, ext, data, sort_key))

    entries.sort(key=lambda x: x[3])

    plan = []  # (original_name, new_name, data)
    video_count = 0
    image_count = 0
    current_prefix = None

    for original_name, ext, data, _ in entries:
        is_video = ext in VIDEO_EXTS
        is_image = ext in IMAGE_EXTS

        if is_video:
            video_count += 1
            current_prefix = f"{video_count:02d}"
            image_count = 0
            # Video is used only as a naming marker — not added to the ZIP
        elif is_image and current_prefix:
            image_count += 1
            if image_count == 1:
                new_name = f"{current_prefix}_INSTALL{ext}"
            else:
                letter = chr(ord('A') + image_count - 2)
                new_name = f"{current_prefix}{letter}{ext}"
            plan.append((original_name, new_name, data))
        # else: images before first video are skipped

    return plan, video_count


def _build_zip(plan) -> bytes:
    # SpooledTemporaryFile spills to disk when compressed output exceeds 50 MB,
    # preventing the ZIP buffer from doubling peak RAM on large batches.
    spool = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024)
    with zipfile.ZipFile(spool, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for _, new_name, data in plan:
            zf.writestr(new_name, data)
    spool.seek(0)
    return spool.read()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

uploaded_files = st.file_uploader(
    "Upload media files",
    type=list(IMAGE_EXTS | {e.lstrip('.') for e in VIDEO_EXTS}),
    accept_multiple_files=True,
    help="Select all video and image files from your camera roll.",
)

sort_order = st.radio(
    "Sort order",
    options=["Date taken (EXIF / metadata)", "File uploader order"],
    horizontal=True,
)
use_upload_order = sort_order == "File uploader order"

if uploaded_files:
    total_mb = sum(uf.size for uf in uploaded_files) / (1024 * 1024)
    if total_mb > 150:
        st.warning(
            f"Total upload is {total_mb:.0f} MB. Consider uploading in smaller batches "
            f"(≤ 150 MB) to avoid running out of memory."
        )

    # Cache the plan so EXIF/hachoir parsing only runs when the file set changes,
    # not on every widget interaction (sort order toggle, etc.).
    _fp = hashlib.md5(
        b"|".join(f"{uf.name}:{uf.size}".encode() for uf in uploaded_files)
        + f"|{use_upload_order}".encode()
    ).hexdigest()
    if st.session_state.get("_plan_fp") != _fp:
        with st.spinner(f"Processing {len(uploaded_files)} file(s)…"):
            st.session_state["_plan"], st.session_state["_video_count"] = _build_plan(uploaded_files, use_upload_order=use_upload_order)
        st.session_state["_plan_fp"] = _fp
    plan = st.session_state["_plan"]
    video_marker_count = st.session_state.get("_video_count", 0)

    skipped = len(uploaded_files) - len(plan) - video_marker_count

    if not plan:
        st.warning("No renameable files found. Make sure you upload at least one video (as a marker) alongside your images.")
    else:
        st.subheader(f"{len(plan)} image(s) will be renamed and zipped")
        if video_marker_count:
            st.caption(f"{video_marker_count} video(s) used as naming markers — excluded from ZIP to save space.")
        if skipped:
            st.caption(f"{skipped} file(s) skipped (images uploaded before any video, or unsupported type).")

        rows = [
            {"Original name": orig, "New name": new}
            for orig, new, _ in plan
        ]
        st.dataframe(rows, use_container_width=True)

        zip_bytes = _build_zip(plan)
        st.download_button(
            label="Download renamed files (.zip)",
            data=zip_bytes,
            file_name="renamed_media.zip",
            mime="application/zip",
            type="primary",
        )
else:
    st.info("Upload video and image files above to get started.")
