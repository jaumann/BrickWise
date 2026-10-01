"""Find the structure of an instruction book from its text and image positions.

LEGO books vary by year, but the building blocks are stable:

* the inventory at the back pairs a count ("4x") with an element ID under a part picture;
* each step has a parts box of pictures with a small "Nx" under each one,
  and a large step number under the box;
* bag starts show a very large bag number;
* repeated sub-builds show a large "Nx" in a box at the start and again
  beside the finished sub-build at the end;
* alternative builds print "go to page" numbers next to a book icon.

Sizes differ between books, so every threshold here is relative to sizes
measured from the book itself.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .model import BagMark, Branch, Callout, InventoryItem, Multiplier, StepMark
from .pdfdoc import Box, Document, Image, Page, Word

COUNT_RE = re.compile(r"^(\d{1,3})x$")
ELEMENT_RE = re.compile(r"^\d{5,8}$")
DIGITS_RE = re.compile(r"^\d{1,4}$")


def _count(word: Word) -> int | None:
    m = COUNT_RE.match(word.text)
    return int(m.group(1)) if m else None


def _rounded(h: float) -> float:
    return round(h * 2) / 2


def _mode(values: list[float]) -> float | None:
    if not values:
        return None
    return Counter(_rounded(v) for v in values).most_common(1)[0][0]


def _near(a: float, b: float, tol: float = 0.15) -> bool:
    return abs(a - b) <= max(1.0, b * tol)


def _same_band(a: Box, b: Box, tol: float = 1.5) -> bool:
    """Tiles cut from one picture share their top and bottom (or left and right)
    edges and overlap slightly. Neighbouring parts in a box never overlap."""
    overlap_x = min(a.x1, b.x1) - max(a.x0, b.x0)
    overlap_y = min(a.y1, b.y1) - max(a.y0, b.y0)
    side_by_side = abs(a.y0 - b.y0) <= tol and abs(a.y1 - b.y1) <= tol and overlap_x > 0.3
    stacked = abs(a.x0 - b.x0) <= tol and abs(a.x1 - b.x1) <= tol and overlap_y > 0.3
    return side_by_side or stacked


def _union(boxes: list[Box]) -> Box:
    return Box(
        min(b.x0 for b in boxes), min(b.y0 for b in boxes), max(b.x1 for b in boxes), max(b.y1 for b in boxes)
    )


@dataclass
class Picture:
    """One part picture, which a PDF may store as several image tiles."""

    tiles: list[Image]

    @property
    def box(self) -> Box:
        return _union([t.box for t in self.tiles])

    @property
    def key(self) -> str:
        return "+".join(sorted({t.key for t in self.tiles}))


def _grow(seed: Image, images: list[Image]) -> Picture:
    tiles = [seed]
    changed = True
    while changed:
        changed = False
        for img in images:
            if img in tiles or img.box.w < 2 or img.box.h < 2:
                continue
            if any(_same_band(img.box, t.box) for t in tiles):
                tiles.append(img)
                changed = True
    return Picture(tiles)


def picture_above(images: list[Image], word: Word, max_gap: float) -> Picture | None:
    """The picture sitting directly above a count label.

    Labels are left-aligned with their picture. Pictures can overlap their
    neighbours and some are stored as several tiles, so tiles that share an
    edge band are joined first, and among the pictures that line up with the
    label the largest one wins.
    """
    slack = word.h
    near = []
    seen: set[str] = set()
    for img in images:
        b = img.box
        if b.h < 2 or b.w < 2:
            continue  # rules and hairlines, not parts
        if b.y1 > word.box.y0 + slack * 0.4:
            continue
        gap = word.box.y0 - b.y1
        if gap > max_gap:
            continue
        pic = _grow(img, images)
        pb = pic.box
        if pic.key in seen or not (pb.x0 - slack <= word.box.x0 <= pb.x1 + slack):
            continue
        seen.add(pic.key)
        near.append((max(word.box.y0 - pb.y1, 0.0), abs(pb.x0 - word.box.x0), pic))
    if not near:
        return None
    aligned = [t for t in near if t[1] <= slack and t[0] <= slack * 1.5]
    if aligned:
        return max(aligned, key=lambda t: t[2].box.w * t[2].box.h)[2]
    return min(near, key=lambda t: t[0] + t[1] * 0.3)[2]


@dataclass
class Metrics:
    callout_h: float  # height of the small "Nx" labels
    step_h: float  # height of main step numbers


class Layout:
    def __init__(self, doc: Document):
        self.doc = doc
        self.n = len(doc)
        self._words: dict[int, list[Word]] = {}
        # picture key -> (page, [(tile key, tile box)])
        self.pictures: dict[str, tuple[int, list[tuple[str, Box]]]] = {}
        self.inventory_pages = self._find_inventory_pages()
        first_inv = self.inventory_pages[0] if self.inventory_pages else self.n + 1
        self.build_pages = list(range(1, first_inv))
        self.metrics = self._measure()

    # -- helpers ---------------------------------------------------------

    def page(self, number: int) -> Page:
        return self.doc.page(number - 1)

    def words(self, number: int) -> list[Word]:
        if number not in self._words:
            self._words[number] = self.page(number).words
            self.doc.release(number - 1)
        return self._words[number]

    def images(self, number: int) -> list[Image]:
        return self.page(number).images

    # -- inventory -------------------------------------------------------

    def _find_inventory_pages(self) -> list[int]:
        pages = []
        for p in range(1, self.n + 1):
            ws = self.words(p)
            ids = sum(1 for w in ws if ELEMENT_RE.match(w.text))
            counts = sum(1 for w in ws if COUNT_RE.match(w.text))
            if ids >= 5 and counts >= 5:
                pages.append(p)
        if not pages:
            return []
        # The inventory is one run of pages at the back.
        run = [pages[-1]]
        for p in reversed(pages[:-1]):
            if run[-1] - p <= 2:
                run.append(p)
            else:
                break
        return sorted(run)

    def inventory(self) -> list[InventoryItem]:
        items = []
        for p in self.inventory_pages:
            ws = self.words(p)
            images = self.images(p)
            ids = [w for w in ws if ELEMENT_RE.match(w.text)]
            for w in ws:
                n = _count(w)
                if n is None:
                    continue
                below = [
                    v
                    for v in ids
                    if -w.h * 0.5 <= v.box.y0 - w.box.y1 <= w.h * 1.5 and abs(v.box.x0 - w.box.x0) <= w.h
                ]
                if not below:
                    continue
                elem = min(below, key=lambda v: abs(v.box.y0 - w.box.y1))
                img = picture_above(images, w, max_gap=w.h * 4)
                if img:
                    self.pictures[img.key] = (p, [(t.key, t.box) for t in img.tiles])
                items.append(
                    InventoryItem(elem.text, n, p, img.key if img else None, img.box if img else None)
                )
        return items

    # -- metrics ---------------------------------------------------------

    def _measure(self) -> Metrics:
        count_hs = [w.h for p in self.build_pages for w in self.words(p) if COUNT_RE.match(w.text)]
        callout_h = _mode(count_hs) or 8.0
        digit_hs = [
            w.h
            for p in self.build_pages
            for w in self.words(p)
            if DIGITS_RE.match(w.text) and w.h > callout_h * 1.6
        ]
        step_h = _mode(digit_hs) or callout_h * 3
        return Metrics(callout_h, step_h)

    # -- steps -----------------------------------------------------------

    def step_marks(self) -> list[StepMark]:
        out = []
        for p in self.build_pages:
            for w in self.words(p):
                if DIGITS_RE.match(w.text) and _near(w.h, self.metrics.step_h, 0.08):
                    out.append(StepMark(p, int(w.text), w.box))
        return out

    def callouts(self, steps: list[StepMark]) -> list[Callout]:
        m = self.metrics
        by_page: dict[int, list[StepMark]] = {}
        for s in steps:
            by_page.setdefault(s.page, []).append(s)
        out = []
        last_step: int | None = None
        for p in self.build_pages:
            page_steps = by_page.get(p, [])
            words = self.words(p)
            if not any(COUNT_RE.match(w.text) for w in words):
                if page_steps:
                    last_step = max(s.number for s in page_steps)
                continue
            images = self.images(p)
            page_w = self.page(p).width
            for w in words:
                n = _count(w)
                if n is None or not _near(w.h, m.callout_h, 0.25):
                    continue
                img = picture_above(images, w, max_gap=w.h * 4)
                if img is None:
                    continue
                self.pictures[img.key] = (p, [(t.key, t.box) for t in img.tiles])
                step = self._step_for_callout(w.box, page_steps, page_w)
                out.append(Callout(p, n, img.key, img.box, w.box, step if step is not None else last_step))
            self.doc.release(p - 1)
            if page_steps:
                last_step = max(s.number for s in page_steps)
        return out

    @staticmethod
    def _step_for_callout(box: Box, page_steps: list[StepMark], page_w: float) -> int | None:
        """A parts box sits just above its step number, left-aligned with it."""
        best, best_d = None, float("inf")
        for s in page_steps:
            dy = s.box.y0 - box.y1
            if dy < -box.h:
                continue
            dx = box.x0 - s.box.x0
            if dx < -box.h * 2 or dx > page_w * 0.45:
                continue
            d = dy + max(0.0, -dx) * 3 + dx * 0.2
            if d < best_d:
                best, best_d = s.number, d
        return best

    # -- bags ------------------------------------------------------------

    def bag_marks(self) -> list[BagMark]:
        cands = []
        for p in self.build_pages:
            for w in self.words(p):
                if DIGITS_RE.match(w.text) and w.h > self.metrics.step_h * 1.25:
                    cands.append(BagMark(p, int(w.text), w.box))
        # Bag numbers run 1, 2, 3 ... through the book. Keep the longest
        # non-decreasing run starting low; stray large digits fall away.
        best: list[list[BagMark]] = []
        for c in cands:
            chain = [c]
            for prev in best:
                step_up = c.number - prev[-1].number
                if 0 <= step_up <= 3 and prev[-1].page < c.page and len(prev) + 1 > len(chain):
                    chain = prev + [c]
            best.append(chain)
        if not best:
            return []
        return max(best, key=lambda ch: (len(ch), -ch[0].number))

    # -- repeated sub-builds -------------------------------------------------

    def multipliers(self, steps: list[StepMark], callouts: list[Callout]) -> list[Multiplier]:
        m = self.metrics
        callouts_by_page: dict[int, list[Callout]] = {}
        for c in callouts:
            callouts_by_page.setdefault(c.page, []).append(c)
        steps_by_page: dict[int, list[StepMark]] = {}
        for s in steps:
            steps_by_page.setdefault(s.page, []).append(s)

        marks: list[tuple[int, Word, str, int | None]] = []
        for p in self.build_pages:
            for w in self.words(p):
                n = _count(w)
                if n is None or n < 2 or w.h < m.step_h * 0.8:
                    continue
                below = [
                    c
                    for c in callouts_by_page.get(p, [])
                    if 0 <= c.image_box.y0 - w.box.y1 <= w.h * 6
                    and w.box.x0 - w.h * 2 <= c.count_box.x0 <= w.box.x1 + w.h * 8
                ]
                if below:
                    first = min(below, key=lambda c: (c.image_box.y0, c.image_box.x0))
                    marks.append((p, w, "start", first.step))
                else:
                    marks.append((p, w, "end", self._step_before(w.box, p, steps_by_page)))

        out = []
        open_start: tuple[int, Word, int | None] | None = None
        for p, w, kind, step in marks:
            n = _count(w)
            if kind == "start":
                open_start = (p, w, step)
            elif open_start is not None and _count(open_start[1]) == n:
                out.append(Multiplier(n, open_start[0], open_start[2], p, step))
                open_start = None
        return out

    @staticmethod
    def _step_before(box: Box, page: int, steps_by_page: dict[int, list[StepMark]]) -> int | None:
        here = [s for s in steps_by_page.get(page, []) if s.box.y0 < box.y1 and s.box.x0 < box.x1]
        if here:
            # The step whose picture holds the marker: nearest number above-left.
            return min(here, key=lambda s: (box.y0 - s.box.y0) + (box.x0 - s.box.x0) * 0.5).number
        prev = [s for q, ss in steps_by_page.items() if q < page for s in ss]
        if prev:
            last_page = max(s.page for s in prev)
            return max(s.number for s in prev if s.page == last_page)
        return None

    # -- alternative builds ------------------------------------------------

    def _page_refs(self, p: int, steps_h: float) -> list[int]:
        refs = []
        for w in self.words(p):
            if not DIGITS_RE.match(w.text) or _near(w.h, steps_h, 0.08):
                continue
            v = int(w.text)
            if p < v <= self.n and w.h < steps_h * 0.8:
                refs.append(v)
        return sorted(set(refs))

    def branches(self) -> list[Branch]:
        out = []
        sh = self.metrics.step_h
        p = 1
        last_build = self.build_pages[-1] if self.build_pages else 0
        while p <= last_build:
            refs = self._page_refs(p, sh)
            if len(refs) >= 2 and refs[0] == p + 1 and refs[-1] <= last_build:
                targets = refs
                rejoin = None
                end_first = targets[1] - 1
                for q in range(targets[0], targets[1]):
                    r = [v for v in self._page_refs(q, sh) if v > targets[-1]]
                    if r:
                        rejoin, end_first = r[0], q
                        break
                segs = [(targets[0], end_first)]
                for i, t in enumerate(targets[1:], start=1):
                    nxt = (
                        targets[i + 1] - 1 if i + 1 < len(targets) else (rejoin - 1 if rejoin else last_build)
                    )
                    segs.append((t, nxt))
                out.append(Branch(p, segs, rejoin))
                p = rejoin or last_build + 1
            else:
                p += 1
        return out

    def set_number(self) -> str | None:
        for w in self.words(1):
            if re.match(r"^\d{4,6}$", w.text):
                return w.text
        return None
