"""Plain data types produced by the parser."""

from __future__ import annotations

from dataclasses import dataclass, field

from .pdfdoc import Box


@dataclass
class InventoryItem:
    element_id: str
    count: int
    page: int  # 1-based
    image_key: str | None
    image_box: Box | None


@dataclass
class Callout:
    """One part picture with its "Nx" count in a step's parts box."""

    page: int  # 1-based
    count: int
    image_key: str
    image_box: Box
    count_box: Box
    step: int | None = None
    element_id: str | None = None
    confidence: float = 0.0  # 0..1, how clearly the best match beat the runner-up
    factor: int = 1  # multiplier from a repeated sub-build, decided during reconciliation


@dataclass
class StepMark:
    page: int
    number: int
    box: Box


@dataclass
class BagMark:
    page: int
    number: int
    box: Box


@dataclass
class Multiplier:
    """A "build this Nx" sub-assembly: start box and end marker."""

    factor: int
    start_page: int
    start_step: int | None
    end_page: int
    end_step: int | None
    applied: bool = False  # True when the step boxes show one copy and must be multiplied


@dataclass
class Branch:
    """Alternative builds: the book splits at `page` and rejoins at `rejoin`."""

    page: int
    segments: list[tuple[int, int]]  # inclusive page ranges, one per alternative
    rejoin: int | None


@dataclass
class Mismatch:
    element_id: str
    inventory: int
    steps: int


@dataclass
class ParsedSet:
    path: str
    set_number: str | None
    page_count: int
    inventory_pages: list[int]
    inventory: list[InventoryItem]
    callouts: list[Callout]
    steps: list[StepMark]
    bags: list[BagMark]
    multipliers: list[Multiplier]
    branches: list[Branch]
    mismatches: list[Mismatch] = field(default_factory=list)

    @property
    def inventory_totals(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in self.inventory:
            out[item.element_id] = out.get(item.element_id, 0) + item.count
        return out

    @property
    def reconciled_lines(self) -> int:
        return len(self.inventory_totals) - len(self.mismatches)

    def _excluded_pages(self, page: int) -> set[int]:
        """Pages on other branches than `page`, which never come before it in a build."""
        out: set[int] = set()
        for br in self.branches:
            mine = next((s for s in br.segments if s[0] <= page <= s[1]), None)
            for seg in br.segments:
                if seg is not mine:
                    out.update(range(seg[0], seg[1] + 1))
        return out

    def bag_for(self, page: int) -> int | None:
        """The bag being built on a page: the latest bag start on the way to it."""
        skip = self._excluded_pages(page)
        marks = [b for b in self.bags if b.page <= page and b.page not in skip]
        return marks[-1].number if marks else None

    def parts_by_bag(self) -> dict[int | None, dict[str, int]]:
        """Pieces of each part per bag. For alternative builds, the larger branch counts."""
        per: dict[tuple[int | None, tuple[int, int]], dict[str, int]] = {}
        for c in self.callouts:
            if c.element_id is None:
                continue
            scope = (-1, 0)
            for bi, br in enumerate(self.branches):
                for si, (a, z) in enumerate(br.segments):
                    if a <= c.page <= z:
                        scope = (bi, si)
            key = (self.bag_for(c.page), scope)
            per.setdefault(key, {})
            per[key][c.element_id] = per[key].get(c.element_id, 0) + c.count * c.factor
        out: dict[int | None, dict[str, int]] = {}
        branch_max: dict[tuple[int | None, int, str], int] = {}
        for (bag, (bi, _si)), parts in per.items():
            for e, n in parts.items():
                if bi < 0:
                    out.setdefault(bag, {})
                    out[bag][e] = out[bag].get(e, 0) + n
                else:
                    k = (bag, bi, e)
                    branch_max[k] = max(branch_max.get(k, 0), n)
        for (bag, _bi, e), n in branch_max.items():
            out.setdefault(bag, {})
            out[bag][e] = out[bag].get(e, 0) + n
        return out
