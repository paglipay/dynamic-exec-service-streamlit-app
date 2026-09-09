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


def pending_job_count(printer_name: str) -> int:
    """How many jobs are currently sitting in `printer_name`'s local
    Windows print queue (Start > "See what's printing", or the tray icon
    that appears while something's printing) -- used to show a real
    count before clear_print_queue's confirmation prompt."""
    hprinter = win32print.OpenPrinter(printer_name)
    try:
        info = win32print.GetPrinter(hprinter, 2)
        return info["cJobs"]
    finally:
        win32print.ClosePrinter(hprinter)


def clear_print_queue(printer_name: str) -> int:
    """Cancels every job currently in `printer_name`'s local Windows print
    queue -- e.g. after a jam, a wrong-printer mistake, or several force-
    print/Print Included jobs piled up unwanted. Best-effort per job (one
    stuck job failing to delete doesn't stop the rest); returns how many
    were actually cleared. Raises only if the printer itself can't be
    opened at all."""
    hprinter = win32print.OpenPrinter(printer_name)
    try:
        info = win32print.GetPrinter(hprinter, 2)
        jobs = win32print.EnumJobs(hprinter, 0, info["cJobs"], 1)
        cleared = 0
        for job in jobs:
            try:
                win32print.SetJob(hprinter, job["JobId"], 0, None, win32print.JOB_CONTROL_DELETE)
                cleared += 1
            except Exception:
                continue
        return cleared
    finally:
        win32print.ClosePrinter(hprinter)


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
