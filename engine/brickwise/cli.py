"""Command-line entry point: `brickwise parse book.pdf`."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import asdict

from .model import ParsedSet
from .parser import parse


def summary(ps: ParsedSet, seconds: float | None = None) -> str:
    inv = ps.inventory_totals
    lines = len(inv)
    ok = ps.reconciled_lines
    pct = 100 * ok / lines if lines else 0
    out = [
        f"{ps.path}",
        (
            f"  set {ps.set_number or '?'} · {ps.page_count} pages · inventory on pages "
            f"{ps.inventory_pages[0]}-{ps.inventory_pages[-1]}"
        ),
        f"  inventory: {lines} parts, {sum(inv.values())} pieces",
        (
            f"  steps: {len({(s.page, s.number) for s in ps.steps})} step numbers, "
            f"{len(ps.callouts)} part pictures, {len(ps.bags)} bags"
        ),
    ]
    if ps.multipliers:
        applied = sum(1 for m in ps.multipliers if m.applied)
        out.append(f"  repeated sub-builds: {len(ps.multipliers)} ({applied} multiplied)")
    for b in ps.branches:
        segs = ", ".join(f"pages {a}-{z}" for a, z in b.segments)
        out.append(f"  alternative builds at page {b.page}: {segs}; rejoin at page {b.rejoin}")
    out.append(f"  reconciled: {ok}/{lines} parts ({pct:.1f}%)" + (f" in {seconds:.1f}s" if seconds else ""))
    for m in ps.mismatches[:15]:
        out.append(f"    {m.element_id}: inventory {m.inventory}, steps {m.steps}")
    if len(ps.mismatches) > 15:
        out.append(f"    ... {len(ps.mismatches) - 15} more")
    return "\n".join(out)


def to_json(ps: ParsedSet) -> dict:
    data = asdict(ps)
    data["mismatches"] = [asdict(m) for m in ps.mismatches]
    return data


def where_used(ps: ParsedSet, element_id: str) -> list[tuple[int, int, int]]:
    """(step, page, count) for every step using a part."""
    agg: dict[tuple[int, int], int] = defaultdict(int)
    for c in ps.callouts:
        if c.element_id == element_id and c.step is not None:
            agg[(c.step, c.page)] += c.count * c.factor
    return sorted((s, p, n) for (s, p), n in agg.items())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="brickwise", description="Parse LEGO building instruction PDFs.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_parse = sub.add_parser("parse", help="parse PDFs and report how well step totals match the inventory")
    p_parse.add_argument("pdf", nargs="+")
    p_parse.add_argument("--json", metavar="FILE", help="write the full result as JSON (one PDF only)")
    p_bags = sub.add_parser("bags", help="list the parts that go in each bag")
    p_bags.add_argument("pdf")
    p_part = sub.add_parser("part", help="list the steps that use a part")
    p_part.add_argument("pdf")
    p_part.add_argument("element_id")
    args = ap.parse_args(argv)

    if args.cmd == "parse":
        if args.json and len(args.pdf) > 1:
            ap.error("--json takes a single PDF")
        for path in args.pdf:
            t = time.time()
            ps = parse(path, progress=lambda s: print(f"  {s}...", file=sys.stderr))
            print(summary(ps, time.time() - t))
            if args.json:
                with open(args.json, "w") as fh:
                    json.dump(to_json(ps), fh, indent=1)
        return 0

    if args.cmd == "bags":
        ps = parse(args.pdf)
        for bag, parts in sorted(ps.parts_by_bag().items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
            label = f"Bag {bag}" if bag is not None else "Before the first bag"
            print(f"{label}: {sum(parts.values())} pieces")
            for e, n in sorted(parts.items(), key=lambda kv: (-kv[1], kv[0])):
                print(f"  {n:>4}x {e}")
        return 0

    if args.cmd == "part":
        ps = parse(args.pdf)
        rows = where_used(ps, args.element_id)
        if not rows:
            print(f"{args.element_id} is not used in any step")
            return 1
        for step, page, n in rows:
            print(f"step {step} (page {page}): {n}x")
        print(f"total {sum(n for _, _, n in rows)}, inventory {ps.inventory_totals.get(args.element_id, 0)}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
