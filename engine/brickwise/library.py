"""The user's library of imported sets: one SQLite database plus pictures.

The library folder holds:

    library.db                   sets, inventories, steps, bags and part pictures per step
    sets/<id>/cover.png          the book's first page, for the library screen
    sets/<id>/pictures/<x>.png   part pictures cut from the PDF
    sets/<id>/pages/<n>.png      pages rendered when the app asks for them

Everything in it comes from PDFs the user imported. Nothing is bundled with the
app and nothing leaves the user's machine.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium

from . import __version__
from .model import BagMark, Branch, Callout, InventoryItem, Mismatch, Multiplier, ParsedSet, StepMark
from .parser import Progress, _quiet, parse
from .pdfdoc import Box
from .reconcile import mismatches, step_totals

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE sets (
    id INTEGER PRIMARY KEY,
    set_number TEXT,
    name TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    pdf_hash TEXT NOT NULL UNIQUE,
    page_count INTEGER NOT NULL,
    inventory_pages TEXT NOT NULL,  -- JSON list of page numbers
    multipliers TEXT NOT NULL,      -- JSON, repeated sub-builds
    branches TEXT NOT NULL,         -- JSON, alternative builds
    engine_version TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE TABLE inventory (
    set_id INTEGER NOT NULL REFERENCES sets(id) ON DELETE CASCADE,
    element_id TEXT NOT NULL,
    count INTEGER NOT NULL,
    page INTEGER NOT NULL,
    picture TEXT,
    PRIMARY KEY (set_id, element_id)
);
CREATE TABLE steps (
    id INTEGER PRIMARY KEY,
    set_id INTEGER NOT NULL REFERENCES sets(id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    page INTEGER NOT NULL
);
CREATE TABLE bags (
    set_id INTEGER NOT NULL REFERENCES sets(id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    page INTEGER NOT NULL
);
-- One part picture with its count in a step's parts box, or a piece the user
-- placed by hand (source 'user'), which counts as 1x.
CREATE TABLE callouts (
    id INTEGER PRIMARY KEY,
    set_id INTEGER NOT NULL REFERENCES sets(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    step INTEGER,
    count INTEGER NOT NULL,
    factor INTEGER NOT NULL DEFAULT 1,
    element_id TEXT,
    confidence REAL NOT NULL DEFAULT 0,
    picture TEXT,
    box TEXT,                            -- JSON [x0, y0, x1, y1] in PDF points, top-down
    candidates TEXT NOT NULL DEFAULT '[]',  -- JSON [[element_id, distance], ...], best first
    source TEXT NOT NULL DEFAULT 'parser',
    edited INTEGER NOT NULL DEFAULT 0     -- 1 once the user changed which part it is
);
CREATE INDEX callouts_set ON callouts(set_id, element_id);
-- Count disagreements the user chose to leave as they are.
CREATE TABLE accepted (
    set_id INTEGER NOT NULL REFERENCES sets(id) ON DELETE CASCADE,
    element_id TEXT NOT NULL,
    PRIMARY KEY (set_id, element_id)
);
"""

COVER_WIDTH = 480
PAGE_WIDTH = 1400
_NO_BOX = Box(0, 0, 0, 0)


class LibraryError(Exception):
    """A problem worth showing to the user as is."""


def file_hash(path: str) -> str:
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def picture_name(key: str) -> str:
    return hashlib.blake2b(key.encode(), digest_size=8).hexdigest() + ".png"


# Background cut-out: pixels this close to the picture's border colour, and
# connected to the border, become transparent.
BG_TOLERANCE = 14


def cut_out(rgb: np.ndarray) -> np.ndarray:
    """BGRA copy of a part picture with its flat background made transparent.

    Inventory and parts-box pictures sit on a plain panel colour. Only the panel
    around the part is removed, so light areas inside the part's outline stay.
    """
    bgr = np.ascontiguousarray(rgb[:, :, ::-1])
    h, w = bgr.shape[:2]
    if h < 4 or w < 4:
        return bgr
    border = np.concatenate([bgr[0], bgr[-1], bgr[:, 0], bgr[:, -1]]).astype(np.int16)
    bg = np.median(border, axis=0)
    if (np.abs(border - bg).max(axis=1) <= BG_TOLERANCE).mean() < 0.6:
        return bgr  # no plain background to remove
    near = (np.abs(bgr.astype(np.int16) - bg).max(axis=2) <= BG_TOLERANCE).astype(np.uint8)
    _n, labels = cv2.connectedComponents(near, connectivity=4)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    background = np.isin(labels, edge[edge != 0])
    alpha = np.where(background, 0, 255).astype(np.uint8)
    return np.dstack([bgr, alpha])


def write_png(path: Path, bgr: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:  # pragma: no cover - only on an empty image
        raise ValueError(f"could not encode {path.name}")
    path.write_bytes(buf.tobytes())


def render_page(pdf_path: str, number: int, width: int) -> tuple[np.ndarray, tuple[float, float]]:
    """Page `number` (1-based) as BGR pixels `width` wide, plus its size in points."""
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        page = pdf[number - 1]
        size = page.get_size()
        pixels = page.render(scale=width / size[0]).to_numpy()
        return pixels[:, :, :3].copy(), size
    finally:
        pdf.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Library:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)
        (self.root / "sets").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "library.db", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self.db.executescript(SCHEMA + f"PRAGMA user_version={SCHEMA_VERSION};")
        elif version > SCHEMA_VERSION:
            raise LibraryError("This library was written by a newer version of BrickWise.")

    def close(self) -> None:
        self.db.close()

    def set_dir(self, set_id: int) -> Path:
        return self.root / "sets" / str(set_id)

    def rel(self, path: Path) -> str:
        """Path relative to the library root, with forward slashes, as the app expects."""
        return path.relative_to(self.root).as_posix()

    def clean_up(self) -> None:
        """Remove half-finished imports, e.g. after a crash. Only call when no import runs."""
        for d in (self.root / "sets").glob(".importing-*"):
            shutil.rmtree(d, ignore_errors=True)

    # -- import ----------------------------------------------------------

    def import_pdf(self, path: str, progress: Progress = _quiet) -> tuple[int, bool]:
        """Parse a PDF into the library. Returns (set id, False) if it was already there."""
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise LibraryError(f"No file at {path}")
        digest = file_hash(path)
        row = self.db.execute("SELECT id FROM sets WHERE pdf_hash = ?", (digest,)).fetchone()
        if row:
            return row["id"], False

        tmp = self.root / "sets" / f".importing-{uuid.uuid4().hex}"
        (tmp / "pictures").mkdir(parents=True)
        try:
            names: dict[str, str] = {}

            def keep(key: str, rgb: np.ndarray) -> None:
                names[key] = picture_name(key)
                write_png(tmp / "pictures" / names[key], cut_out(rgb))

            ps = parse(path, progress, pictures=keep)
            progress("saving", 1.0)
            write_png(tmp / "cover.png", render_page(path, 1, COVER_WIDTH)[0])
            return self._insert(ps, digest, names, tmp), True
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    def _insert(self, ps: ParsedSet, digest: str, names: dict[str, str], tmp: Path) -> int:
        name = f"Set {ps.set_number}" if ps.set_number else Path(ps.path).stem
        with self.db:
            set_id = self.db.execute(
                "INSERT INTO sets (set_number, name, pdf_path, pdf_hash, page_count, inventory_pages,"
                " multipliers, branches, engine_version, imported_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    ps.set_number,
                    name,
                    ps.path,
                    digest,
                    ps.page_count,
                    json.dumps(ps.inventory_pages),
                    json.dumps([asdict(m) for m in ps.multipliers]),
                    json.dumps([asdict(b) for b in ps.branches]),
                    __version__,
                    _now(),
                ),
            ).lastrowid
            inventory: dict[str, list] = {}
            for item in ps.inventory:
                pic = names.get(item.image_key) if item.image_key else None
                if item.element_id in inventory:
                    inventory[item.element_id][1] += item.count
                    inventory[item.element_id][3] = inventory[item.element_id][3] or pic
                else:
                    inventory[item.element_id] = [item.element_id, item.count, item.page, pic]
            self.db.executemany(
                "INSERT INTO inventory (set_id, element_id, count, page, picture) VALUES (?,?,?,?,?)",
                [(set_id, *v) for v in inventory.values()],
            )
            self.db.executemany(
                "INSERT INTO steps (set_id, number, page) VALUES (?,?,?)",
                [(set_id, s.number, s.page) for s in ps.steps],
            )
            self.db.executemany(
                "INSERT INTO bags (set_id, number, page) VALUES (?,?,?)",
                [(set_id, b.number, b.page) for b in ps.bags],
            )
            self.db.executemany(
                "INSERT INTO callouts (set_id, page, step, count, factor, element_id, confidence,"
                " picture, box, candidates) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        set_id,
                        c.page,
                        c.step,
                        c.count,
                        c.factor,
                        c.element_id,
                        round(c.confidence, 4),
                        names.get(c.image_key),
                        json.dumps([round(v, 2) for v in asdict(c.image_box).values()]),
                        json.dumps([[e, round(d, 4)] for d, e in ps.candidates.get(c.image_key, [])]),
                    )
                    for c in ps.callouts
                ],
            )
            target = self.set_dir(set_id)
            if target.exists():  # left over from an id SQLite has since reused
                shutil.rmtree(target)
            os.replace(tmp, target)
        return set_id

    # -- reading ---------------------------------------------------------

    def _set_row(self, set_id: int) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM sets WHERE id = ?", (set_id,)).fetchone()
        if row is None:
            raise LibraryError("That set is no longer in the library.")
        return row

    def _load(self, row: sqlite3.Row) -> ParsedSet:
        """Rebuild the parse result from the database, including the user's edits."""
        set_id = row["id"]
        q = self.db.execute
        callouts = [
            Callout(
                page=r["page"],
                count=r["count"],
                image_key=str(r["id"]),
                image_box=_NO_BOX,
                count_box=_NO_BOX,
                step=r["step"],
                element_id=r["element_id"],
                confidence=r["confidence"],
                factor=r["factor"],
            )
            for r in q("SELECT * FROM callouts WHERE set_id = ? ORDER BY id", (set_id,))
        ]
        branches = [
            Branch(b["page"], [tuple(s) for s in b["segments"]], b["rejoin"])
            for b in json.loads(row["branches"])
        ]
        ps = ParsedSet(
            path=row["pdf_path"],
            set_number=row["set_number"],
            page_count=row["page_count"],
            inventory_pages=json.loads(row["inventory_pages"]),
            inventory=[
                InventoryItem(r["element_id"], r["count"], r["page"], None, None)
                for r in q("SELECT * FROM inventory WHERE set_id = ? ORDER BY rowid", (set_id,))
            ],
            callouts=callouts,
            steps=[
                StepMark(r["page"], r["number"], _NO_BOX)
                for r in q("SELECT * FROM steps WHERE set_id = ? ORDER BY page, id", (set_id,))
            ],
            bags=[
                BagMark(r["page"], r["number"], _NO_BOX)
                for r in q("SELECT * FROM bags WHERE set_id = ? ORDER BY page, rowid", (set_id,))
            ],
            multipliers=[Multiplier(**m) for m in json.loads(row["multipliers"])],
            branches=branches,
        )
        ps.mismatches = mismatches(ps.inventory_totals, callouts, branches)
        return ps

    def _accepted(self, set_id: int) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT element_id FROM accepted WHERE set_id = ?", (set_id,))}

    def _summary(self, row: sqlite3.Row, ps: ParsedSet) -> dict:
        totals = ps.inventory_totals
        accepted = self._accepted(row["id"])
        cover = self.set_dir(row["id"]) / "cover.png"
        return {
            "id": row["id"],
            "set_number": row["set_number"],
            "name": row["name"],
            "pdf_path": row["pdf_path"],
            "pdf_found": os.path.isfile(row["pdf_path"]),
            "page_count": row["page_count"],
            "imported_at": row["imported_at"],
            "parts": len(totals),
            "pieces": sum(totals.values()),
            "bags": len({b.number for b in ps.bags}),
            "reconciled": len(totals) - sum(1 for m in ps.mismatches if m.element_id in totals),
            "to_check": sum(1 for m in ps.mismatches if m.element_id not in accepted),
            "cover": self.rel(cover) if cover.exists() else None,
        }

    def list_sets(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM sets ORDER BY imported_at DESC, id DESC").fetchall()
        return [self._summary(r, self._load(r)) for r in rows]

    def _pictures(self, set_id: int) -> str:
        return f"sets/{set_id}/pictures/"

    def get_set(self, set_id: int) -> dict:
        """A set with its inventory and how many of each part go in each bag."""
        row = self._set_row(set_id)
        ps = self._load(row)
        accepted = self._accepted(set_id)
        off = {m.element_id for m in ps.mismatches}
        by_bag = ps.parts_by_bag()
        pics = self._pictures(set_id)
        inventory = []
        for r in self.db.execute("SELECT * FROM inventory WHERE set_id = ? ORDER BY rowid", (set_id,)):
            e = r["element_id"]
            bags = sorted((b, parts[e]) for b, parts in by_bag.items() if b is not None and parts.get(e))
            inventory.append(
                {
                    "element_id": e,
                    "count": r["count"],
                    "page": r["page"],
                    "picture": pics + r["picture"] if r["picture"] else None,
                    "bags": bags,
                    "no_bag": max(0, r["count"] - sum(n for _, n in bags)),
                    "status": "ok" if e not in off else "accepted" if e in accepted else "check",
                }
            )
        out = self._summary(row, ps)
        out["bag_list"] = self._bags(set_id)
        out["inventory"] = inventory
        return out

    def _bags(self, set_id: int) -> list[dict]:
        seen: dict[int, int] = {}
        for r in self.db.execute("SELECT number, page FROM bags WHERE set_id = ? ORDER BY page", (set_id,)):
            seen.setdefault(r["number"], r["page"])
        return [{"number": n, "page": p} for n, p in sorted(seen.items())]

    # -- review ----------------------------------------------------------

    def review(self, set_id: int) -> dict:
        """Every part whose step total disagrees with the inventory, with the evidence."""
        row = self._set_row(set_id)
        ps = self._load(row)
        accepted = self._accepted(set_id)
        totals = step_totals(ps.callouts, ps.branches)
        pics = self._pictures(set_id)
        inv = {
            r["element_id"]: r
            for r in self.db.execute("SELECT * FROM inventory WHERE set_id = ?", (set_id,)).fetchall()
        }

        def pic(name: str | None) -> str | None:
            return pics + name if name else None

        # Parts that still disagree, plus parts the user already fixed so they can see
        # (and undo) their changes.
        touched = [
            r[0]
            for r in self.db.execute(
                "SELECT DISTINCT element_id FROM callouts WHERE set_id = ? AND (source = 'user' OR edited = 1)"
                " ORDER BY element_id",
                (set_id,),
            )
        ]
        open_ = {m.element_id for m in ps.mismatches}
        todo = ps.mismatches + [
            Mismatch(e, ps.inventory_totals.get(e, 0), totals.get(e, 0)) for e in touched if e not in open_
        ]
        items = []
        for m in todo:
            rows = self.db.execute(
                "SELECT * FROM callouts WHERE set_id = ? AND element_id = ? ORDER BY page, step, id",
                (set_id, m.element_id),
            ).fetchall()
            groups: dict[str, dict] = {}
            placed = []
            for r in rows:
                if r["source"] == "user":
                    placed.append(
                        {"id": r["id"], "page": r["page"], "step": r["step"], "bag": ps.bag_for(r["page"])}
                    )
                    continue
                g = groups.get(r["picture"])
                if g is None:
                    g = groups[r["picture"]] = {
                        "picture": pic(r["picture"]),
                        "confidence": r["confidence"],
                        "edited": bool(r["edited"]),
                        "pieces": 0,
                        "uses": [],
                        "candidates": [
                            {
                                "element_id": e,
                                "picture": pic(inv[e]["picture"]),
                                "inventory": inv[e]["count"],
                                "steps": totals.get(e, 0),
                            }
                            for e, _d in json.loads(r["candidates"])
                            if e != m.element_id and e in inv
                        ][:5],
                    }
                g["pieces"] += r["count"] * r["factor"]
                g["uses"].append(
                    {
                        "id": r["id"],
                        "page": r["page"],
                        "step": r["step"],
                        "count": r["count"],
                        "factor": r["factor"],
                        "box": json.loads(r["box"]) if r["box"] else None,
                    }
                )
            i = inv.get(m.element_id)
            items.append(
                {
                    "element_id": m.element_id,
                    "inventory": m.inventory,
                    "steps": m.steps,
                    "unplaced": not groups and m.inventory > 0,
                    "ok": m.element_id not in open_,
                    "accepted": m.element_id in accepted,
                    "picture": pic(i["picture"]) if i else None,
                    "page": i["page"] if i else None,
                    "groups": sorted(groups.values(), key=lambda g: g["confidence"]),
                    "placed": placed,
                    "suspects": [],
                }
            )
        # A part that comes up short is often a look-alike of one that comes up
        # over: offer the over-counted part's step pictures that list it as a
        # close match.
        for item in items:
            if item["steps"] >= item["inventory"]:
                continue
            for other in items:
                if other is item or other["steps"] <= other["inventory"] or other["ok"]:
                    continue
                for g in other["groups"]:
                    if any(c["element_id"] == item["element_id"] for c in g["candidates"]):
                        item["suspects"].append({**g, "matched_to": other["element_id"]})
        steps = [
            {"id": r["id"], "number": r["number"], "page": r["page"], "bag": ps.bag_for(r["page"])}
            for r in self.db.execute("SELECT * FROM steps WHERE set_id = ? ORDER BY page, id", (set_id,))
        ]
        return {
            "set": self._summary(row, ps),
            "items": items,
            "bags": self._bags(set_id),
            "steps": steps,
            "parts": [
                {"element_id": e, "picture": pic(r["picture"]), "inventory": r["count"]}
                for e, r in inv.items()
            ],
        }

    def reassign(self, set_id: int, picture: str, element_id: str) -> dict:
        """Say which part a step picture really is. Applies to every step that uses the picture."""
        self._set_row(set_id)
        if not self.db.execute(
            "SELECT 1 FROM inventory WHERE set_id = ? AND element_id = ?", (set_id, element_id)
        ).fetchone():
            raise LibraryError(f"{element_id} is not in this set's inventory.")
        name = picture.rsplit("/", 1)[-1]
        with self.db:
            n = self.db.execute(
                "UPDATE callouts SET element_id = ?, edited = 1 WHERE set_id = ? AND picture = ? AND source = 'parser'",
                (element_id, set_id, name),
            ).rowcount
        if not n:
            raise LibraryError("That picture is not in this set.")
        return self.review(set_id)

    def place(self, set_id: int, element_id: str, step_id: int | None = None, bag: int | None = None) -> dict:
        """Add one piece of a part to a step, or to a bag without a particular step."""
        self._set_row(set_id)
        if step_id is not None:
            r = self.db.execute(
                "SELECT number, page FROM steps WHERE set_id = ? AND id = ?", (set_id, step_id)
            ).fetchone()
            if r is None:
                raise LibraryError("That step is not in this set.")
            step, page = r["number"], r["page"]
        elif bag is not None:
            r = self.db.execute(
                "SELECT MIN(page) AS page FROM bags WHERE set_id = ? AND number = ?", (set_id, bag)
            ).fetchone()
            if r["page"] is None:
                raise LibraryError(f"This set has no bag {bag}.")
            step, page = None, r["page"]
        else:
            raise LibraryError("Choose a step or a bag.")
        with self.db:
            self.db.execute(
                "INSERT INTO callouts (set_id, page, step, count, element_id, confidence, source)"
                " VALUES (?,?,?,1,?,1,'user')",
                (set_id, page, step, element_id),
            )
        return self.review(set_id)

    def unplace(self, set_id: int, callout_id: int) -> dict:
        with self.db:
            self.db.execute(
                "DELETE FROM callouts WHERE set_id = ? AND id = ? AND source = 'user'", (set_id, callout_id)
            )
        return self.review(set_id)

    def accept(self, set_id: int, element_id: str | None = None, accepted: bool = True) -> dict:
        """Leave a count disagreement as it is (or undo that). No element = every open one."""
        row = self._set_row(set_id)
        ids = [element_id] if element_id else [m.element_id for m in self._load(row).mismatches]
        with self.db:
            if accepted:
                self.db.executemany(
                    "INSERT OR IGNORE INTO accepted (set_id, element_id) VALUES (?,?)",
                    [(set_id, e) for e in ids],
                )
            else:
                self.db.executemany(
                    "DELETE FROM accepted WHERE set_id = ? AND element_id = ?", [(set_id, e) for e in ids]
                )
        return self.review(set_id)

    # -- housekeeping ----------------------------------------------------

    def rename(self, set_id: int, name: str) -> dict:
        name = name.strip()
        if not name:
            raise LibraryError("A set needs a name.")
        self._set_row(set_id)
        with self.db:
            self.db.execute("UPDATE sets SET name = ? WHERE id = ?", (name, set_id))
        return self.get_set(set_id)

    def delete(self, set_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM sets WHERE id = ?", (set_id,))
        shutil.rmtree(self.set_dir(set_id), ignore_errors=True)

    def page_image(self, set_id: int, page: int) -> dict:
        """A rendered page of the set's PDF, cached in the library."""
        row = self._set_row(set_id)
        if not 1 <= page <= row["page_count"]:
            raise LibraryError(f"This book has no page {page}.")
        out = self.set_dir(set_id) / "pages" / f"{page}.png"
        meta = out.with_suffix(".json")
        if not (out.exists() and meta.exists()):
            if not os.path.isfile(row["pdf_path"]):
                raise LibraryError(f"The PDF is no longer at {row['pdf_path']}.")
            pixels, size = render_page(row["pdf_path"], page, PAGE_WIDTH)
            out.parent.mkdir(exist_ok=True)
            write_png(out, pixels)
            meta.write_text(json.dumps({"width": size[0], "height": size[1]}))
        return {
            "path": self.rel(out),
            "page": page,
            "page_count": row["page_count"],
            **json.loads(meta.read_text()),
        }
