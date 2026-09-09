"""label.py — Renders a camera asset label as a PIL image.

2in x 1in at 300 DPI -- the real label stock size (Dymo/Zebra-style
small labels), sized to match. printing.py scales whatever image this
produces to fill the printer's page while preserving aspect ratio, so
this file is the one place label dimensions need to change.

At this size there's no room for a fixed layout that also handles both
a short camera number ("CAM6") and force-print's "UNASSIGNED"
placeholder (see camera_barcode_scan.py) without either wasting space
or clipping -- every line below is sized via _fit_font, which picks
the largest font that still fits its band, so short text fills the
available area and long text shrinks instead of overflowing.

No barcode yet — just the fields a technician needs to read by eye.
Add one later (e.g. `python-barcode` or `qrcode`) once real label
stock/printer specs are known.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

DPI = 300
WIDTH_IN = 2.0
HEIGHT_IN = 1.0
WIDTH_PX = int(WIDTH_IN * DPI)   # 600
HEIGHT_PX = int(HEIGHT_IN * DPI)  # 300

MARGIN = 12


@dataclass
class LabelData:
    camera_number: str          # e.g. "CAM06" or "—" if unassigned
    serial_number: str
    model_number: str
    site_name: str
    loc_code: str = ""
    # Not part of the fixed 5-slot layout render_label draws below --
    # available purely as a {ip_address} placeholder value (see
    # templates.py) for a template that folds it into one of the other
    # slots (e.g. Model Number field customized to "IP: {ip_address}").
    # Real Live Mode broker jobs don't carry this yet -- see print_agent.py.
    ip_address: str = ""


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Best-effort: use a bundled Windows font if available, else PIL's
    built-in default (which ignores `size`, so scale via image size
    instead in that fallback case). Every fixed-layout call site below
    wants bold (the original, still-default behavior); only the free-form
    layout editor's per-element Bold toggle ever passes bold=False."""
    candidates = ("arialbd.ttf", "seguisb.ttf") if bold else ("arial.ttf", "segoeui.ttf")
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fit_font(
    draw: ImageDraw.ImageDraw, text: str, max_width: int, max_height: int,
    max_size: int, min_size: int = 10,
) -> ImageFont.FreeTypeFont:
    """Largest font size (down to min_size, step 2) whose rendered bounding
    box fits within max_width x max_height. Lets a short string (a normal
    "CAM06") fill however much of its band the text actually needs, while
    a long one (force-print's "UNASSIGNED", a long serial) shrinks to fit
    instead of clipping or overflowing the label."""
    size = max_size
    while size > min_size:
        font = _font(size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        if (right - left) <= max_width and (bottom - top) <= max_height:
            return font
        size -= 2
    return _font(min_size)


def render_label(data: LabelData) -> Image.Image:
    img = Image.new("RGB", (WIDTH_PX, HEIGHT_PX), "white")
    draw = ImageDraw.Draw(img)

    usable_w = WIDTH_PX - 2 * MARGIN
    y = MARGIN

    # Header: site name + loc code sharing one line -- the least critical
    # field at this size, so it gets the smallest band and shrinks first.
    header = data.site_name or ""
    if data.loc_code:
        header = f"{header}  ({data.loc_code})" if header else data.loc_code
    if header:
        header_font = _fit_font(draw, header, usable_w, 24, max_size=22, min_size=11)
        draw.text((MARGIN, y), header, font=header_font, fill="black")
        y += header_font.size + 4

    draw.line((MARGIN, y, WIDTH_PX - MARGIN, y), fill="black", width=2)
    y += 5

    # Camera number: the dominant element on the label -- centered in a
    # fixed-height band sized to whatever font width the text needs, up to
    # nearly the full label width.
    cam_band_h = 140
    cam_text = data.camera_number or "—"
    cam_font = _fit_font(draw, cam_text, usable_w, cam_band_h, max_size=170, min_size=28)
    draw.text((WIDTH_PX / 2, y + cam_band_h / 2), cam_text, font=cam_font, fill="black", anchor="mm")
    y += cam_band_h + 4

    draw.line((MARGIN, y, WIDTH_PX - MARGIN, y), fill="black", width=2)
    y += 6

    # Model / Serial -- split whatever height remains into two lines,
    # abbreviated ("M:"/"S:" not "Model:"/"Serial:") to leave more width
    # for the value itself, each shrunk to fit independently.
    remaining_h = HEIGHT_PX - MARGIN - y
    line_h = remaining_h // 2

    model_text = f"M: {data.model_number}"
    model_font = _fit_font(draw, model_text, usable_w, line_h - 4, max_size=36, min_size=14)
    draw.text((MARGIN, y), model_text, font=model_font, fill="black")
    y += line_h

    serial_text = f"S: {data.serial_number}"
    serial_font = _fit_font(draw, serial_text, usable_w, line_h - 4, max_size=36, min_size=14)
    draw.text((MARGIN, y), serial_text, font=serial_font, fill="black")

    draw.rectangle((2, 2, WIDTH_PX - 2, HEIGHT_PX - 2), outline="black", width=2)
    return img


def render_label_custom(elements: list[dict]) -> Image.Image:
    """Renders a template's free-form layout (see the "layout" key in
    templates.py's docstring) -- each element independently positioned,
    instead of render_label's fixed header/camera#/model/serial bands.

    Each element: {"text", "x", "y", "font_size", "align", "bold"}. x/y
    are in this label's native 600x300 (2in x 1in @ 300dpi) pixel space --
    WIDTH_PX/HEIGHT_PX above -- resolution-independent of whatever scale
    the layout editor's canvas displays them at. (x, y) is the vertical
    center of the text, at its left/center/right edge per `align` -- a
    natural drag handle, and avoids baseline-vs-top ambiguity.

    Unlike render_label's _fit_font, nothing here auto-shrinks to fit --
    that would fight a tool whose whole point is direct manual control.
    An element positioned or sized to run off the label's edge just does;
    the editor's own preview makes that visible before it's printed.

    `text` is expected already placeholder-resolved by the caller (see
    print_agent.py's _print_templates) -- this module stays a pure
    renderer with no knowledge of the placeholder/template system."""
    img = Image.new("RGB", (WIDTH_PX, HEIGHT_PX), "white")
    draw = ImageDraw.Draw(img)
    anchors = {"left": "lm", "center": "mm", "right": "rm"}
    for el in elements:
        font = _font(int(el.get("font_size", 24)), bold=el.get("bold", True))
        anchor = anchors.get(el.get("align", "left"), "lm")
        draw.text(
            (el.get("x", 0), el.get("y", 0)), el.get("text", ""),
            font=font, fill="black", anchor=anchor,
        )
    draw.rectangle((2, 2, WIDTH_PX - 2, HEIGHT_PX - 2), outline="black", width=2)
    return img


if __name__ == "__main__":
    # Quick manual check: renders a sample label to label_preview.png.
    sample = LabelData(
        camera_number="CAM06",
        serial_number="B8A44F9C9745",
        model_number="P3827-PVE",
        site_name="Will Rogers Continuation High",
        loc_code="8895",
    )
    render_label(sample).save("label_preview.png")
    print("Wrote label_preview.png")
