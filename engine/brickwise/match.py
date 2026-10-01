"""Compare part pictures from step boxes with the inventory pictures.

The same part is drawn with the same render in both places, but at different
sizes, on different backgrounds and with JPEG noise. Pictures are compared
after cropping to the part, replacing the background with neutral grey and
scaling to a small common size.

Shape alone cannot tell a 1x12 plate from a 1x16 plate, but size can: every
step box in a book is drawn at one scale and the inventory at another. Once
that ratio is known (estimated from confident matches) the drawn size of a
part is a strong extra cue.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

SIZE = 24
NEUTRAL = 128
BG_THRESHOLD = 30

ASPECT_WEIGHT = 0.03
SHAPE_WEIGHT = 0.05
SIZE_WEIGHT = 0.03


@dataclass
class Feature:
    pixels: np.ndarray  # SIZE x SIZE x 3 float32 in 0..1, part centred on neutral grey
    mask: np.ndarray  # SIZE x SIZE float32, 1 where the part is
    aspect: float  # width / height of the cropped part
    size: float  # drawn size of the part in PDF points (sqrt of area of its box)


def feature(rgb: np.ndarray, width_pt: float, height_pt: float) -> Feature | None:
    if rgb.size == 0 or min(rgb.shape[:2]) < 2:
        return None
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    diff = np.abs(rgb.astype(np.int32) - bg.astype(np.int32)).sum(axis=2)
    on = diff > BG_THRESHOLD
    ys, xs = np.where(on)
    if len(ys) == 0:
        return None
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = rgb[y0:y1, x0:x1].copy()
    cmask = on[y0:y1, x0:x1]
    crop[~cmask] = NEUTRAL
    h, w = crop.shape[:2]
    side = max(h, w)
    canvas = np.full((side, side, 3), NEUTRAL, np.uint8)
    mcanvas = np.zeros((side, side), np.float32)
    oy, ox = (side - h) // 2, (side - w) // 2
    canvas[oy : oy + h, ox : ox + w] = crop
    mcanvas[oy : oy + h, ox : ox + w] = cmask
    px = cv2.resize(canvas, (SIZE, SIZE), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    mk = cv2.resize(mcanvas, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    sx = width_pt / rgb.shape[1]
    sy = height_pt / rgb.shape[0]
    size = math.sqrt(max(w * sx * h * sy, 1e-6))
    return Feature(px, mk, w / h, size)


def distance(a: Feature, b: Feature, scale: float | None = None) -> float:
    """How different two part pictures look; `scale` is step size / inventory size."""
    colour = float(np.mean((a.pixels - b.pixels) ** 2))
    shape = float(np.mean((a.mask - b.mask) ** 2))
    d = colour + SHAPE_WEIGHT * shape + ASPECT_WEIGHT * abs(math.log(a.aspect / b.aspect))
    if scale:
        d += SIZE_WEIGHT * abs(math.log(a.size / (b.size * scale)))
    return d


def rank(
    query: Feature, candidates: dict[str, Feature], scale: float | None = None, top: int = 6
) -> list[tuple[float, str]]:
    scored = sorted((distance(query, f, scale), key) for key, f in candidates.items())
    return scored[:top]


def estimate_scale(pairs: list[tuple[Feature, Feature]]) -> float | None:
    """Median size ratio of confidently matched (step, inventory) pictures."""
    ratios = [a.size / b.size for a, b in pairs if b.size > 0]
    if len(ratios) < 5:
        return None
    return float(np.median(ratios))
