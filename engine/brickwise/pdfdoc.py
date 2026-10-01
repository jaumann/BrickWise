"""Thin wrapper over pypdfium2 that yields words and images per page.

All coordinates are in PDF points with the origin at the top-left of the page
(y grows downwards), which is how people read instruction pages.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import cached_property

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as raw


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(frozen=True)
class Word:
    text: str
    box: Box

    @property
    def h(self) -> float:
        return self.box.h


@dataclass
class Image:
    box: Box
    key: str  # hash of the encoded image data; identical pictures share a key
    _obj: object = field(repr=False, compare=False)

    def pixels(self) -> np.ndarray:
        """Decoded RGB pixels as an (h, w, 3) uint8 array."""
        bitmap = self._obj.get_bitmap(render=False)
        arr = bitmap.to_numpy()
        fmt = bitmap.format
        if arr.ndim == 2:
            arr = np.repeat(arr[:, :, None], 3, axis=2)
        elif fmt in (raw.FPDFBitmap_BGR, raw.FPDFBitmap_BGRx, raw.FPDFBitmap_BGRA):
            arr = arr[:, :, 2::-1] if arr.shape[2] >= 3 else arr
        return np.ascontiguousarray(arr[:, :, :3])


class Page:
    def __init__(self, page: pdfium.PdfPage, index: int):
        self._page = page
        self.index = index
        self.width, self.height = page.get_size()

    @property
    def number(self) -> int:
        """1-based page number, as a PDF viewer shows it."""
        return self.index + 1

    @cached_property
    def words(self) -> list[Word]:
        tp = self._page.get_textpage()
        n = tp.count_chars()
        words: list[Word] = []
        cur: list[tuple[str, tuple[float, float, float, float]]] = []

        def flush() -> None:
            if not cur:
                return
            text = "".join(c for c, _ in cur)
            x0 = min(b[0] for _, b in cur)
            x1 = max(b[2] for _, b in cur)
            y0 = min(b[1] for _, b in cur)
            y1 = max(b[3] for _, b in cur)
            box = Box(x0, self.height - y1, x1, self.height - y0)
            # Ignore text parked outside the visible page.
            if box.x0 < self.width and box.x1 > 0 and box.y0 < self.height and box.y1 > 0:
                words.append(Word(text, box))
            cur.clear()

        for i in range(n):
            ch = chr(raw.FPDFText_GetUnicode(tp, i))
            if ch.isspace() or ch == "\x00":
                flush()
                continue
            left, bottom, right, top = tp.get_charbox(i, loose=True)
            if cur:
                prev = cur[-1][1]
                # A jump back, a gap, or a different line starts a new word.
                tall = max(top - bottom, prev[3] - prev[1], 1.0)
                if left < prev[0] - 1 or left - prev[2] > tall * 0.6 or abs(bottom - prev[1]) > tall * 0.3:
                    flush()
            cur.append((ch, (left, bottom, right, top)))
        flush()
        # Some PDFs draw the same text twice (outline + fill); keep one copy.
        seen: set[tuple[str, int, int]] = set()
        unique = []
        for w in words:
            k = (w.text, round(w.box.x0), round(w.box.y0))
            if k not in seen:
                seen.add(k)
                unique.append(w)
        return unique

    @cached_property
    def images(self) -> list[Image]:
        out = []
        for obj in self._page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=6):
            left, bottom, right, top = obj.get_bounds()
            try:
                data = obj.get_data(decode_simple=False)
                key = hashlib.blake2b(bytes(data), digest_size=12).hexdigest()
            except Exception:  # pragma: no cover - exotic image encodings
                w, h = obj.get_px_size()
                key = f"anon-{self.index}-{len(out)}-{w}x{h}"
            out.append(Image(Box(left, self.height - top, right, self.height - bottom), key, obj))
        return out


class Document:
    def __init__(self, path: str):
        self.path = path
        self._pdf = pdfium.PdfDocument(path)
        self._pages: dict[int, Page] = {}

    def __len__(self) -> int:
        return len(self._pdf)

    def page(self, index: int) -> Page:
        if index not in self._pages:
            self._pages[index] = Page(self._pdf[index], index)
        return self._pages[index]

    def pages(self):
        for i in range(len(self)):
            yield self.page(i)

    def release(self, index: int) -> None:
        """Drop a cached page to keep memory flat on very large books."""
        self._pages.pop(index, None)
