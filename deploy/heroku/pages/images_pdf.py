"""
images_pdf.py — Streamlit page that turns zip(s) of images into PDFs.

Upload one or more .zip files containing images. Each zip is rendered to
a multi-page PDF: a configurable-column grid of thumbnails with the
filename as a caption under each one. If 2+ zips are uploaded you also
get a "combined" PDF spanning everything, and a batch download of all
per-zip PDFs as a single .zip.

Layout / sizing / sort behavior mirrors paramiko/pdf_images.py so the
output looks like the existing camera_views PDFs.
"""

import io
import re
import zipfile
from pathlib import Path
from typing import Optional

import streamlit as st
from PIL import Image as PILImage, ImageOps
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

# ── Config ────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Images → PDF", page_icon="📄")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp"}

PAGE_SIZES = {
    "Letter (8.5 × 11 in)": letter,
    "A4 (210 × 297 mm)":    A4,
}

# Cap on bytes per uploaded zip we'll attempt to process. Large enough
# for thousands of camera-view JPGs, small enough that one malicious
# upload can't OOM the dyno.
MAX_ZIP_BYTES = 500 * 1024 * 1024  # 500 MB


# ── Helpers ───────────────────────────────────────────────────────────────────

def _natural_key(name: str):
    """Sort key that orders 'IMG_2' before 'IMG_10' (numeric-aware)."""
    parts = re.split(r"(\d+)", Path(name).stem.upper())
    return [int(x) if x.isdigit() else x for x in parts]


def _thumb_bytes(img_bytes: bytes, max_px: int, quality: int) -> tuple[bytes, int, int]:
    """Return downsampled-JPEG bytes + (w, h). Applies EXIF rotation."""
    with PILImage.open(io.BytesIO(img_bytes)) as im:
        # exif_transpose so portrait photos come out portrait in the PDF
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_px, max_px), PILImage.LANCZOS)
        w, h = im.size
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue(), w, h


def extract_images_from_zip(zip_bytes: bytes) -> list[tuple[str, bytes]]:
    """
    Pull every image entry out of a zip and return [(filename, bytes), ...]
    sorted naturally by filename. Directories, dotfiles, and macOS
    resource forks (__MACOSX/, ._*) are skipped. Nested folders are
    flattened — only the basename is kept.
    """
    images: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            base = Path(name).name
            if not base or base.startswith("."):
                continue
            if name.startswith("__MACOSX/"):
                continue
            if Path(base).suffix.lower() not in IMAGE_EXTS:
                continue
            with zf.open(info) as fh:
                images.append((base, fh.read()))
    images.sort(key=lambda x: _natural_key(x[0]))
    return images


def build_pdf(
    images: list[tuple[str, bytes]],
    *,
    columns: int,
    page_size,
    margin: float,
    thumb_max_px: int,
    jpeg_quality: int,
    show_captions: bool,
    max_cell_height_in: float = 2.5,
    caption_font_size: int = 7,
    caption_leading: int = 9,
) -> bytes:
    """
    Render `images` to a PDF and return its bytes.

    The layout is a Table of cells, `columns` per row, with each cell
    holding a thumbnail and (optionally) a centered filename caption.
    Mirrors paramiko/pdf_images.py so output is consistent with the
    existing camera_views PDFs.
    """
    if not images:
        raise ValueError("No images to render")

    page_w, _page_h = page_size
    usable_w = page_w - 2 * margin
    col_w = usable_w / columns
    img_w_max = col_w - 0.15 * inch  # small horizontal padding inside the column
    max_h = max_cell_height_in * inch

    styles = getSampleStyleSheet()
    caption_style = ParagraphStyle(
        "caption",
        parent=styles["Normal"],
        fontSize=caption_font_size,
        leading=caption_leading,
        alignment=TA_CENTER,
        wordWrap="LTR",
    )

    def make_cell(name: str, data: bytes) -> list:
        try:
            jpeg_data, tw, th = _thumb_bytes(data, thumb_max_px, jpeg_quality)
        except Exception as exc:
            # Don't kill the whole PDF for one bad image — show a stub.
            return [Paragraph(f"[error: {name}: {exc}]", caption_style)]

        aspect = (th / tw) if tw else 1.0
        disp_h = img_w_max * aspect
        if disp_h > max_h:
            disp_h = max_h
            disp_w = disp_h / aspect
        else:
            disp_w = img_w_max

        rl_img = Image(io.BytesIO(jpeg_data), width=disp_w, height=disp_h)
        rl_img.hAlign = "CENTER"
        cell: list = [rl_img]
        if show_captions:
            cell.append(Spacer(1, 2))
            cell.append(Paragraph(Path(name).stem, caption_style))
        return cell

    cells = [make_cell(n, d) for n, d in images]

    # Pad final row so the Table has a uniform shape
    remainder = len(cells) % columns
    if remainder:
        cells += [[]] * (columns - remainder)
    rows = [cells[i : i + columns] for i in range(0, len(cells), columns)]

    table = Table(rows, colWidths=[col_w] * columns)
    table.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=page_size,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )
    doc.build([table])
    return buf.getvalue()


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("📄 Images → PDF")
st.caption(
    "Upload zip(s) of images → get a multi-page PDF per zip, plus a combined "
    "PDF if you upload more than one. Layout matches the camera_views PDFs."
)

# ── Settings (apply to all uploaded zips) ─────────────────────────────────────
with st.expander("⚙️ Settings", expanded=False):
    c1, c2 = st.columns(2)
    columns = c1.slider("Columns", min_value=1, max_value=5, value=3)
    page_size_name = c2.selectbox(
        "Page size", options=list(PAGE_SIZES.keys()), index=0,
    )
    page_size = PAGE_SIZES[page_size_name]

    c3, c4 = st.columns(2)
    thumb_max_px = c3.slider(
        "Thumbnail max px (longest side)",
        min_value=200, max_value=1600, value=600, step=50,
        help="Smaller = smaller PDF and faster generation. 600 is a good default.",
    )
    jpeg_quality = c4.slider(
        "JPEG quality", min_value=30, max_value=95, value=75, step=5,
        help="Higher = better-looking but larger PDF.",
    )

    c5, c6 = st.columns(2)
    margin_in = c5.slider(
        "Page margin (inches)", min_value=0.25, max_value=1.5,
        value=0.5, step=0.25,
    )
    max_cell_height_in = c6.slider(
        "Max cell height (inches)", min_value=1.5, max_value=4.5,
        value=2.5, step=0.25,
        help="Caps tall images so they don't dominate a row.",
    )

    show_captions = st.checkbox(
        "Show filename caption under each image", value=True
    )

margin = margin_in * inch

# ── File uploader (rotating key so we can reset on demand) ────────────────────
if "_pdf_uploader_key" not in st.session_state:
    st.session_state["_pdf_uploader_key"] = 0

uploaded_files = st.file_uploader(
    "Upload ZIP file(s) of images",
    type=["zip"],
    accept_multiple_files=True,
    key=f"pdf_uploader_{st.session_state['_pdf_uploader_key']}",
)

if not uploaded_files:
    st.info("Upload one or more .zip files to get started.")
    st.stop()

# ── Extract everything up-front (cached in session_state) ─────────────────────
# Doing this eagerly means the Combined tab always has data — no need to
# visit each per-zip tab first.
for uf in uploaded_files:
    if uf.size > MAX_ZIP_BYTES:
        st.error(
            f"{uf.name} is too large ({uf.size/1e6:.1f} MB > "
            f"{MAX_ZIP_BYTES/1e6:.0f} MB cap). Skipping."
        )
        continue
    fid = f"{uf.name}__{uf.size}"
    images_key = f"pdf_images_{fid}"
    if images_key in st.session_state:
        continue
    with st.spinner(f"Reading {uf.name}…"):
        try:
            st.session_state[images_key] = extract_images_from_zip(uf.getvalue())
        except zipfile.BadZipFile:
            st.session_state[images_key] = None  # sentinel for "bad zip"

# ── Tabs: one per zip, plus a Combined tab when 2+ are present ────────────────
tab_labels = [uf.name for uf in uploaded_files]
combined_active = len(uploaded_files) > 1
if combined_active:
    tab_labels.append("📚 Combined")

tabs = st.tabs(tab_labels)


def _render_zip_tab(tab, uf):
    """One per-zip tab: show count, mini preview, Build button, download."""
    with tab:
        fid = f"{uf.name}__{uf.size}"
        images_key = f"pdf_images_{fid}"
        pdf_key = f"pdf_bytes_{fid}"

        images = st.session_state.get(images_key)
        if images is None:
            st.error(f"`{uf.name}` is not a valid ZIP file.")
            return
        if not images:
            st.warning(f"No image files found in `{uf.name}`.")
            return

        st.write(f"**{len(images)}** image(s) found in `{uf.name}`.")

        # Show a small grid preview of the first few images.
        with st.expander("🔎 Preview first 12 images", expanded=False):
            preview_cols = st.columns(4)
            for i, (name, data) in enumerate(images[:12]):
                with preview_cols[i % 4]:
                    st.image(data, caption=name, use_container_width=True)

        col_build, col_dl = st.columns([1, 1])

        if col_build.button("📄 Build PDF", key=f"build_{fid}"):
            with st.spinner("Generating PDF…"):
                try:
                    st.session_state[pdf_key] = build_pdf(
                        images,
                        columns=columns,
                        page_size=page_size,
                        margin=margin,
                        thumb_max_px=thumb_max_px,
                        jpeg_quality=jpeg_quality,
                        show_captions=show_captions,
                        max_cell_height_in=max_cell_height_in,
                    )
                except Exception as exc:
                    st.error(f"PDF generation failed: {exc}")

        if pdf_key in st.session_state:
            zip_stem = Path(uf.name).stem or "images"
            with col_dl:
                st.download_button(
                    label="⬇️ Download PDF",
                    data=st.session_state[pdf_key],
                    file_name=f"{zip_stem}.pdf",
                    mime="application/pdf",
                    key=f"dl_{fid}",
                )


def _render_combined_tab(tab):
    """Aggregate images across all zips into a single PDF."""
    with tab:
        all_images: list[tuple[str, bytes]] = []
        bad_zips: list[str] = []
        for uf in uploaded_files:
            fid = f"{uf.name}__{uf.size}"
            images = st.session_state.get(f"pdf_images_{fid}")
            if images is None:
                bad_zips.append(uf.name)
                continue
            all_images.extend(images)

        if bad_zips:
            st.warning(f"Skipping invalid zip(s): {', '.join(bad_zips)}")
        if not all_images:
            st.info("No images extracted yet.")
            return

        # Re-sort across all zips so the natural order is global, not per-zip.
        all_images.sort(key=lambda x: _natural_key(x[0]))
        st.write(
            f"**{len(all_images)}** image(s) across **{len(uploaded_files)}** zip(s)."
        )

        combined_key = "pdf_bytes_combined"
        col_build, col_dl = st.columns([1, 1])

        if col_build.button("📄 Build combined PDF", key="build_combined"):
            with st.spinner("Generating combined PDF…"):
                try:
                    st.session_state[combined_key] = build_pdf(
                        all_images,
                        columns=columns,
                        page_size=page_size,
                        margin=margin,
                        thumb_max_px=thumb_max_px,
                        jpeg_quality=jpeg_quality,
                        show_captions=show_captions,
                        max_cell_height_in=max_cell_height_in,
                    )
                except Exception as exc:
                    st.error(f"PDF generation failed: {exc}")

        if combined_key in st.session_state:
            with col_dl:
                st.download_button(
                    label="⬇️ Download combined PDF",
                    data=st.session_state[combined_key],
                    file_name="combined.pdf",
                    mime="application/pdf",
                    key="dl_combined",
                )


# Render every tab
for tab, uf in zip(tabs[: len(uploaded_files)], uploaded_files):
    _render_zip_tab(tab, uf)
if combined_active:
    _render_combined_tab(tabs[-1])


# ── Batch ZIP download (when 2+ per-zip PDFs are ready) ───────────────────────
ready: list[tuple[str, bytes]] = []
for uf in uploaded_files:
    fid = f"{uf.name}__{uf.size}"
    pk = f"pdf_bytes_{fid}"
    if pk in st.session_state:
        stem = Path(uf.name).stem or "images"
        ready.append((f"{stem}.pdf", st.session_state[pk]))

if len(ready) >= 2:
    st.divider()
    current_set = frozenset(n for n, _ in ready)
    if st.session_state.get("_pdf_zip_set") != current_set:
        st.session_state.pop("_pdf_zip_data", None)
        st.session_state["_pdf_zip_set"] = current_set

    if "_pdf_zip_data" not in st.session_state:
        if st.button(
            "🗜️ Prepare ZIP of all PDFs",
            help="Bundles all generated PDFs into a single .zip download.",
        ):
            zip_buf = io.BytesIO()
            # ZIP_STORED — PDFs are already mostly incompressible
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_STORED) as zf:
                for name, data in ready:
                    zf.writestr(name, data)
            st.session_state["_pdf_zip_data"] = zip_buf.getvalue()
            st.rerun()
    else:
        st.download_button(
            label=f"⬇️ Download all {len(ready)} PDF(s) (.zip)",
            data=st.session_state["_pdf_zip_data"],
            file_name="pdfs.zip",
            mime="application/zip",
            key="dl_pdf_batch_zip",
        )
