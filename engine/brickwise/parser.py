"""Turn an instruction PDF into a ParsedSet."""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np

from .layout import Layout
from .match import Feature, estimate_scale, feature, rank
from .model import ParsedSet
from .pdfdoc import Box, Document, Image
from .reconcile import Reconciler

# Called with the current stage and the overall fraction done (0..1).
Progress = Callable[[str, float], None]
# Called once per part picture with its key and RGB pixels, for callers that keep them.
PictureSink = Callable[[str, np.ndarray], None]


def _quiet(_stage: str, _done: float) -> None:
    pass


def compose(images: list[Image], tiles: list[tuple[str, Box]]) -> tuple[Box, np.ndarray | None]:
    """Paste a picture's tiles back together at the finest resolution among them."""
    found = []
    for key, box in tiles:
        img = next(
            (
                i
                for i in images
                if i.key == key and abs(i.box.x0 - box.x0) < 0.5 and abs(i.box.y0 - box.y0) < 0.5
            ),
            None,
        )
        if img is not None:
            found.append((img, img.pixels()))
    if not found:
        return Box(0, 0, 0, 0), None
    union = Box(
        min(i.box.x0 for i, _ in found),
        min(i.box.y0 for i, _ in found),
        max(i.box.x1 for i, _ in found),
        max(i.box.y1 for i, _ in found),
    )
    if len(found) == 1:
        return union, found[0][1]
    ppt = max(px.shape[1] / max(i.box.w, 1e-3) for i, px in found)
    w = max(2, round(union.w * ppt))
    h = max(2, round(union.h * ppt))
    # Start from the first tile's corner colour so gaps read as background.
    canvas = np.empty((h, w, 3), np.uint8)
    canvas[:] = found[0][1][0, 0]
    for img, px in found:
        x0 = round((img.box.x0 - union.x0) * ppt)
        y0 = round((img.box.y0 - union.y0) * ppt)
        tw = max(1, min(w - x0, round(img.box.w * ppt)))
        th = max(1, min(h - y0, round(img.box.h * ppt)))
        canvas[y0 : y0 + th, x0 : x0 + tw] = cv2.resize(px, (tw, th), interpolation=cv2.INTER_AREA)
    return union, canvas


def parse(
    path: str,
    progress: Progress = _quiet,
    debug: dict | None = None,
    pictures: PictureSink | None = None,
) -> ParsedSet:
    """Parse one instruction PDF. Pass a dict as `debug` to get intermediate data back."""
    doc = Document(path)
    try:
        return _parse(doc, path, progress, debug, pictures)
    finally:
        # Close the PDF so it isn't held open (on Windows, locked) after parsing.
        # With `debug`, the caller may still read pages through the returned layout.
        if debug is None:
            doc.close()


def _parse(
    doc: Document, path: str, progress: Progress, debug: dict | None, pictures: PictureSink | None
) -> ParsedSet:
    # Fractions roughly follow where the time goes on a large book.
    progress("reading text", 0.0)
    layout = Layout(doc)
    if not layout.inventory_pages:
        raise ValueError("No parts inventory found. Is this a LEGO building instruction PDF?")

    progress("reading inventory", 0.09)
    inventory = layout.inventory()
    steps = layout.step_marks()
    progress("finding steps", 0.2)
    callouts = layout.callouts(steps)
    bags = layout.bag_marks()
    multipliers = layout.multipliers(steps, callouts)
    branches = layout.branches()

    progress("matching part pictures", 0.26)
    needed = {i.image_key for i in inventory if i.image_key} | {c.image_key for c in callouts}
    needed_steps = {c.image_key for c in callouts}
    by_page: dict[int, list[str]] = {}
    for key in needed:
        by_page.setdefault(layout.pictures[key][0], []).append(key)
    feats: dict[str, Feature | None] = {}
    pages = sorted(by_page)
    for n, p in enumerate(pages, 1):
        images = layout.page(p).images
        for key in by_page[p]:
            box, rgb = compose(images, layout.pictures[key][1])
            feats[key] = feature(rgb, box.w, box.h) if rgb is not None else None
            if pictures is not None and rgb is not None:
                pictures(key, rgb)
        doc.release(p - 1)
        progress("matching part pictures", 0.26 + 0.72 * n / len(pages))

    inv_feats: dict[str, Feature] = {}
    for item in inventory:
        f = feats.get(item.image_key) if item.image_key else None
        if f is not None and item.element_id not in inv_feats:
            inv_feats[item.element_id] = f

    # First pass on looks alone, then again with the drawn-size cue once the
    # book's step-to-inventory scale is known from the clearest matches.
    candidates = {}
    for key in needed_steps:
        f = feats.get(key)
        candidates[key] = rank(f, inv_feats) if f is not None else []
    confident = [
        (feats[k], inv_feats[c[0][1]])
        for k, c in candidates.items()
        if len(c) >= 2 and c[0][0] < 0.5 * c[1][0]
    ]
    scale = estimate_scale(confident)
    if scale:
        for key in needed_steps:
            f = feats.get(key)
            if f is not None:
                candidates[key] = rank(f, inv_feats, scale)
    callouts = [c for c in callouts if candidates.get(c.image_key)]

    progress("checking totals against the inventory", 0.98)
    totals: dict[str, int] = {}
    for item in inventory:
        totals[item.element_id] = totals.get(item.element_id, 0) + item.count
    mismatches = Reconciler(totals, callouts, candidates, multipliers, branches).run()
    if debug is not None:
        debug.update(layout=layout, feats=feats, inv_feats=inv_feats, candidates=candidates, scale=scale)

    return ParsedSet(
        path=path,
        set_number=layout.set_number(),
        page_count=len(doc),
        inventory_pages=layout.inventory_pages,
        inventory=inventory,
        callouts=callouts,
        steps=steps,
        bags=bags,
        multipliers=multipliers,
        branches=branches,
        mismatches=mismatches,
        candidates={c.image_key: candidates[c.image_key] for c in callouts},
    )
