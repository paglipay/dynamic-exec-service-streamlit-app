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
    "Upload video and image files. They are sorted by date taken and renamed using the scheme: "
    "`01.mp4`, `01_INSTALL.jpg`, `01A.jpg`, `01B.jpg`, `02.mp4`, … "
    "Download the result as a ZIP."
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
    try:
        from hachoir.parser import createParser
        from hachoir.metadata import extractMetadata
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
        import os
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
# Rename-plan builder (works entirely in memory)
# ---------------------------------------------------------------------------


def _build_plan(uploaded_files):
    """
    Returns list of (original_name, new_name, bytes) for every file that gets
    a new name.  Files that are unchanged are still included so the ZIP is complete.
    """
    entries = []
    for i, uf in enumerate(uploaded_files):
        ext = Path(uf.name).suffix.lower()
        if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
            continue
        data = uf.getvalue()
        taken = _taken_time(data, ext, i)
        entries.append((uf.name, ext, data, taken))

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
            new_name = f"{current_prefix}{ext}"
            image_count = 0
        elif is_image and current_prefix:
            image_count += 1
            if image_count == 1:
                new_name = f"{current_prefix}_INSTALL{ext}"
            else:
                letter = chr(ord('A') + image_count - 2)
                new_name = f"{current_prefix}{letter}{ext}"
        else:
            continue  # skip images before first video

        plan.append((original_name, new_name, data))

    return plan


def _build_zip(plan) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for _, new_name, data in plan:
            zf.writestr(new_name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

uploaded_files = st.file_uploader(
    "Upload media files",
    type=list(IMAGE_EXTS | {e.lstrip('.') for e in VIDEO_EXTS}),
    accept_multiple_files=True,
    help="Select all video and image files from your camera roll.",
)

if uploaded_files:
    with st.spinner(f"Processing {len(uploaded_files)} file(s)…"):
        plan = _build_plan(uploaded_files)

    skipped = len(uploaded_files) - len(plan)

    if not plan:
        st.warning("No renameable files found. Make sure you upload at least one video.")
    else:
        st.subheader(f"{len(plan)} file(s) will be renamed")
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
