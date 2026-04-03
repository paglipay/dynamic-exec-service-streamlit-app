import os
from pathlib import Path
from datetime import datetime

import streamlit as st
from _auth_guard import require_authentication

st.set_page_config(page_title="Camera Media Renamer")
require_authentication("Camera Media Renamer")
st.title("Camera Media Renamer")
st.caption(
    "Renames video and image files in a folder using a sequential scheme: "
    "`01.mp4`, `01_INSTALL.jpg`, `01A.jpg`, `01B.jpg`, `02.mp4`, …"
)

# ---------------------------------------------------------------------------
# Date-extraction helpers (inline – no external media_date_utils dependency)
# ---------------------------------------------------------------------------

VIDEO_EXTS = {'.mov', '.mp4', '.avi', '.mkv', '.wmv', '.flv', '.mpeg', '.mpg'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}


def _get_image_date_taken(path: str):
    """Return the EXIF DateTimeOriginal as a float timestamp, or None."""
    try:
        from PIL import Image, ExifTags
        with Image.open(path) as img:
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


def _get_video_date_taken(path: str):
    """Return video creation time as a float timestamp, or None."""
    # Try hachoir first
    try:
        from hachoir.parser import createParser
        from hachoir.metadata import extractMetadata
        parser = createParser(path)
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
    return None


def _get_taken_time(path: str, ext: str):
    if ext in IMAGE_EXTS:
        t = _get_image_date_taken(path)
    elif ext in VIDEO_EXTS:
        t = _get_video_date_taken(path)
    else:
        t = None
    return t if t is not None else os.stat(path).st_mtime


def _build_rename_plan(folder: str):
    """Return list of (src_path, dst_path) pairs, skipping no-ops."""
    entries = []
    try:
        for entry in os.scandir(folder):
            if not entry.is_file():
                continue
            ext = Path(entry.name).suffix.lower()
            if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
                continue
            taken = _get_taken_time(entry.path, ext)
            entries.append((entry.path, ext, taken))
    except PermissionError as exc:
        raise exc

    entries.sort(key=lambda x: x[2])

    plan = []
    video_count = 0
    image_count = 0
    current_prefix = None

    for src, ext, _ in entries:
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

        dst = os.path.join(folder, new_name)
        if os.path.abspath(src) != os.path.abspath(dst):
            plan.append((src, dst))

    return plan


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

folder = st.text_input("Folder path", placeholder="/path/to/media/folder")

col_scan, col_reset = st.columns([1, 5])
scan_clicked = col_scan.button("Scan", use_container_width=True)

if scan_clicked:
    folder = folder.strip()
    if not folder:
        st.warning("Please enter a folder path.")
    elif not os.path.isdir(folder):
        st.error(f"Directory not found: `{folder}`")
    else:
        with st.spinner("Scanning files…"):
            try:
                plan = _build_rename_plan(folder)
                st.session_state["rename_plan"] = plan
                st.session_state["rename_folder"] = folder
                st.session_state["rename_done"] = False
            except PermissionError as exc:
                st.error(f"Permission denied: {exc}")
                st.session_state.pop("rename_plan", None)

if "rename_plan" in st.session_state and not st.session_state.get("rename_done"):
    plan = st.session_state["rename_plan"]
    scanned_folder = st.session_state["rename_folder"]

    if not plan:
        st.info("No files need renaming in the selected folder.")
    else:
        st.subheader(f"{len(plan)} file(s) to rename")

        rows = [
            {
                "Current name": os.path.basename(src),
                "New name": os.path.basename(dst),
            }
            for src, dst in plan
        ]
        st.dataframe(rows, use_container_width=True)

        # Conflict check: warn if a destination already exists and is not a source
        sources = {os.path.abspath(s) for s, _ in plan}
        conflicts = [
            dst for _, dst in plan
            if os.path.exists(dst) and os.path.abspath(dst) not in sources
        ]
        if conflicts:
            st.warning(
                f"{len(conflicts)} destination file(s) already exist and would be overwritten:\n"
                + "\n".join(f"- `{os.path.basename(c)}`" for c in conflicts)
            )

        if st.button("Rename files", type="primary"):
            errors = []
            renamed = 0
            progress = st.progress(0)
            for i, (src, dst) in enumerate(plan):
                try:
                    os.rename(src, dst)
                    renamed += 1
                except OSError as exc:
                    errors.append(f"`{os.path.basename(src)}` → `{os.path.basename(dst)}`: {exc}")
                progress.progress((i + 1) / len(plan))

            st.session_state["rename_done"] = True
            st.session_state["rename_results"] = (renamed, errors)
            st.rerun()

if st.session_state.get("rename_done"):
    renamed, errors = st.session_state.get("rename_results", (0, []))
    st.success(f"Renamed {renamed} file(s) successfully.")
    if errors:
        st.error("Some files could not be renamed:")
        for e in errors:
            st.write(f"- {e}")
    if st.button("Start over"):
        for key in ("rename_plan", "rename_folder", "rename_done", "rename_results"):
            st.session_state.pop(key, None)
        st.rerun()
