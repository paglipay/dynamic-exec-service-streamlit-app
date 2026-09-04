"""label.py — Renders a camera asset label as a PIL image.

Size/DPI are placeholders until a real label printer + stock size is
chosen (see project notes on the printing intention). 4in x 2in at
300 DPI is a common small-label size (e.g. Dymo/Zebra shipping-style
labels) and prints legibly to a full sheet via "Microsoft Print to
PDF" too, which is what we're testing against for now.

No barcode yet — just the fields a technician needs to read by eye.
Add one later (e.g. `python-barcode` or `qrcode`) once real label
stock/printer specs are known; the layout below leaves room for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

DPI = 300
WIDTH_IN = 4.0
HEIGHT_IN = 2.0
WIDTH_PX = int(WIDTH_IN * DPI)
HEIGHT_PX = int(HEIGHT_IN * DPI)

MARGIN = 40


@dataclass
class LabelData:
    camera_number: str          # e.g. "CAM06" or "—" if unassigned
    serial_number: str
    model_number: str
    site_name: str
    loc_code: str = ""


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Best-effort: use a bundled Windows font if available, else PIL's
    built-in default (which ignores `size`, so scale via image size
    instead in that fallback case)."""
    for candidate in ("arialbd.ttf", "arial.ttf", "seguisb.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_label(data: LabelData) -> Image.Image:
    img = Image.new("RGB", (WIDTH_PX, HEIGHT_PX), "white")
    draw = ImageDraw.Draw(img)

    y = MARGIN
    draw.text((MARGIN, y), data.site_name, font=_font(38), fill="black")
    y += 52

    if data.loc_code:
        draw.text((MARGIN, y), f"Loc Code: {data.loc_code}", font=_font(28), fill="black")
        y += 42

    draw.line((MARGIN, y, WIDTH_PX - MARGIN, y), fill="black", width=3)
    y += 24

    draw.text((MARGIN, y), "CAMERA #", font=_font(28), fill="black")
    y += 34
    draw.text((MARGIN, y), data.camera_number or "—", font=_font(110), fill="black")
    y += 140

    draw.text((MARGIN, y), f"Model:  {data.model_number}", font=_font(32), fill="black")
    y += 46
    draw.text((MARGIN, y), f"Serial: {data.serial_number}", font=_font(32), fill="black")

    draw.rectangle((4, 4, WIDTH_PX - 4, HEIGHT_PX - 4), outline="black", width=2)
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
