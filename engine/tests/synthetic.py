"""Build small fake instruction books for tests.

Real LEGO PDFs can't live in this repository, so tests draw their own: simple
coloured shapes stand in for parts, laid out the way LEGO books lay out parts
boxes, step numbers, bag starts, repeated sub-builds and the inventory.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image as PILImage
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = 420.0, 300.0
BG = (225, 228, 230)
STEP_SCALE = 1.0  # parts boxes draw parts at full size...
INV_SCALE = 0.75  # ...and the inventory a bit smaller, as real books do.

# element id -> (shape, colour, width, height) at step size in points
PARTS: dict[str, tuple[str, tuple[int, int, int], float, float]] = {
    "3001021": ("brick", (200, 30, 30), 40, 24),
    "302301": ("plate", (30, 70, 200), 48, 12),
    "4211415": ("round", (240, 200, 20), 22, 22),
    "4119477": ("wedge", (40, 150, 60), 34, 26),
    "4211388": ("plate", (90, 90, 90), 32, 12),
}


def part_pixels(element: str, scale: float, ppt: float = 3.0) -> np.ndarray:
    shape, colour, w, h = PARTS[element]
    pw, ph = int(w * scale * ppt) + 8, int(h * scale * ppt) + 8
    img = np.zeros((ph, pw, 3), np.uint8)
    img[:] = BG
    x0, y0, x1, y1 = 4, 4, pw - 5, ph - 5
    dark = tuple(int(c * 0.6) for c in colour)
    if shape in ("brick", "plate"):
        cv2.rectangle(img, (x0, y0), (x1, y1), colour, -1)
        cv2.rectangle(img, (x0, y0), (x1, y1), dark, 2)
        studs = max(1, (x1 - x0) // 24)
        for i in range(studs):
            cx = x0 + (i + 0.5) * (x1 - x0) / studs
            cv2.circle(img, (int(cx), y0 + (y1 - y0) // 3), max(2, (y1 - y0) // 5), dark, -1)
    elif shape == "round":
        cv2.ellipse(
            img, ((x0 + x1) // 2, (y0 + y1) // 2), ((x1 - x0) // 2, (y1 - y0) // 2), 0, 0, 360, colour, -1
        )
        cv2.circle(img, ((x0 + x1) // 2, (y0 + y1) // 2), (x1 - x0) // 5, dark, -1)
    else:
        pts = np.array([[x0, y1], [x1, y1], [x0, y0]], np.int32)
        cv2.fillPoly(img, [pts], colour)
        cv2.polylines(img, [pts], True, dark, 2)
    return img


def _image(
    c: canvas.Canvas, pixels: np.ndarray, x: float, top: float, ppt: float = 3.0
) -> tuple[float, float]:
    """Draw pixels with their top-left corner at (x, top) in top-down page coordinates."""
    h, w = pixels.shape[:2]
    wpt, hpt = w / ppt, h / ppt
    c.drawImage(ImageReader(PILImage.fromarray(pixels)), x, PAGE_H - top - hpt, wpt, hpt)
    return wpt, hpt


def _text(c: canvas.Canvas, s: str, x: float, top: float, size: float) -> None:
    c.setFont("Helvetica", size)
    c.drawString(x, PAGE_H - top - size * 0.8, s)


@dataclass
class Step:
    number: int
    parts: list[tuple[str, int]]  # (element id, count shown in the parts box)


@dataclass
class Book:
    set_number: str = "99901"
    pages: list[list] = field(
        default_factory=list
    )  # each page: list of ("bag", n) / Step / ("mult-start"|"mult-end", n)
    inventory: dict[str, int] = field(default_factory=dict)


def default_book() -> Book:
    """Two bags, a repeated sub-build shown per copy, and an inventory that adds up."""
    b = Book()
    b.pages = [
        [("bag", 1)],
        [Step(1, [("3001021", 2), ("302301", 1)]), Step(2, [("4211415", 4)])],
        [Step(3, [("4119477", 1), ("302301", 2)])],
        # Build this twice: the parts boxes show one copy.
        [("mult-start", 2), Step(4, [("4211388", 1), ("4211415", 1)])],
        [Step(5, [("3001021", 1)]), ("mult-end", 2)],
        [("bag", 2)],
        [Step(6, [("302301", 3), ("4119477", 2)]), Step(7, [("4211388", 2)])],
    ]
    b.inventory = {"3001021": 4, "302301": 6, "4211415": 6, "4119477": 3, "4211388": 4}
    return b


def write_book(path: str, book: Book) -> None:
    c = canvas.Canvas(path, pagesize=(PAGE_W, PAGE_H))
    _text(c, book.set_number, 20, 20, 16)
    c.showPage()
    for n, items in enumerate(book.pages, start=2):
        x = 20.0
        top = 20.0
        for item in items:
            if isinstance(item, Step):
                _draw_step(c, item, x, top)
                x += 200
            elif item[0] == "bag":
                _text(c, str(item[1]), PAGE_W / 2 - 20, PAGE_H / 2 - 40, 72)
            elif item[0] == "mult-start":
                # A box with a preview and a big "Nx"; the step's parts box sits below it.
                c.rect(x, PAGE_H - top - 34, 90, 34)
                _text(c, f"{item[1]}x", x + 48, top + 6, 24)
                top += 44
            elif item[0] == "mult-end":
                _text(c, f"{item[1]}x", PAGE_W - 80, PAGE_H - 70, 40)
        _text(c, str(n), PAGE_W - 30, PAGE_H - 16, 8)
        c.showPage()
    _draw_inventory(c, book.inventory)
    c.showPage()
    c.save()


def _draw_step(c: canvas.Canvas, step: Step, x: float, top: float) -> None:
    px = x + 6
    tallest = max(PARTS[e][3] for e, _ in step.parts) * STEP_SCALE + 8 / 3
    for element, count in step.parts:
        pixels = part_pixels(element, STEP_SCALE)
        wpt, hpt = _image(c, pixels, px, top + 6 + tallest - pixels.shape[0] / 3)
        _text(c, f"{count}x", px, top + 8 + tallest, 7)
        px += wpt + 10
    box_h = tallest + 20
    c.rect(x, PAGE_H - top - box_h, px - x, box_h)
    _text(c, str(step.number), x, top + box_h + 6, 28)


def _draw_inventory(c: canvas.Canvas, inventory: dict[str, int]) -> None:
    x, top = 20.0, 20.0
    for element, count in inventory.items():
        pixels = part_pixels(element, INV_SCALE)
        _, hpt = _image(c, pixels, x, top)
        _text(c, f"{count}x", x, top + hpt + 1, 7)
        _text(c, element, x, top + hpt + 9, 7)
        x += 70
        if x > PAGE_W - 70:
            x, top = 20.0, top + 60
