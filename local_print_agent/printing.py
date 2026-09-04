"""printing.py — Windows printer enumeration + sending a PIL image to a
selected printer via raw GDI drawing (win32print/win32ui), so it works
against any installed printer — physical or virtual — without relying
on file-type associations or a "print" shell verb.

Known behavior, not a bug: "Microsoft Print to PDF" is a real Windows
printer driver that pops its own "Save Print Output As" dialog on every
job, even when printed to via this API — that's the driver's own UI,
outside this code's control. Expect that dialog during testing; a real
label printer won't have it.
"""

from __future__ import annotations

from typing import List

import win32con
import win32print
import win32ui
from PIL import Image, ImageWin


def list_printers() -> List[str]:
    """Local + connected (network) printers, as displayed names."""
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return sorted(p[2] for p in win32print.EnumPrinters(flags))


def default_printer() -> str | None:
    try:
        return win32print.GetDefaultPrinter()
    except Exception:
        return None


def print_image(printer_name: str, image: Image.Image, job_name: str = "Camera Label") -> None:
    """Send a PIL image to `printer_name`, scaled to fill the printable
    area while preserving aspect ratio. Raises on failure — caller
    decides how to surface that (this module has no UI of its own)."""
    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(printer_name)

    printable_w = hdc.GetDeviceCaps(win32con.HORZRES)
    printable_h = hdc.GetDeviceCaps(win32con.VERTRES)

    scale = min(printable_w / image.width, printable_h / image.height)
    draw_w, draw_h = int(image.width * scale), int(image.height * scale)

    hdc.StartDoc(job_name)
    hdc.StartPage()

    dib = ImageWin.Dib(image)
    dib.draw(hdc.GetHandleOutput(), (0, 0, draw_w, draw_h))

    hdc.EndPage()
    hdc.EndDoc()
    hdc.DeleteDC()
