"""Check step totals against the inventory and fix what the evidence supports.

Every picture in a step box is matched to its closest inventory picture. The
counts from all steps are then added up per part and compared with the
inventory. Three things are decided here using that comparison:

* whether each repeated sub-build's step boxes show one copy (multiply) or
  already show the total (leave as is);
* for alternative builds, each part's total is the larger of the branches,
  not their sum, since the box holds parts for whichever version you build;
* look-alike parts that were swapped: a picture is moved to its runner-up
  match when that makes the totals agree and the runner-up is nearly as close.
"""

from __future__ import annotations

from collections import defaultdict

from .model import Branch, Callout, Mismatch, Multiplier

# A picture may move to a runner-up match only if it is nearly as close.
MAX_RATIO = 3.0
MIN_SLACK = 0.004
# Small tie-breaker so that, between equally good totals, closer matches win.
DIST_WEIGHT = 5.0


Scope = tuple[int, int]  # (branch index, segment index); (-1, 0) = shared pages


def scope_of(page: int, branches: list[Branch]) -> Scope:
    for bi, br in enumerate(branches):
        for si, (a, b) in enumerate(br.segments):
            if a <= page <= b:
                return (bi, si)
    return (-1, 0)


def in_region(c: Callout, m: Multiplier) -> bool:
    lo = (m.start_page, m.start_step if m.start_step is not None else -1)
    hi = (m.end_page, m.end_step if m.end_step is not None else 10**9)
    here = (c.page, c.step if c.step is not None else (lo[1] if c.page == m.start_page else hi[1]))
    return lo <= here <= hi


def step_totals(callouts: list[Callout], branches: list[Branch]) -> dict[str, int]:
    """Pieces per part across all steps, as decided (element, factor) on each callout."""
    per: dict[str, dict[Scope, int]] = defaultdict(lambda: defaultdict(int))
    for c in callouts:
        if c.element_id is not None:
            per[c.element_id][scope_of(c.page, branches)] += c.count * c.factor
    return {e: Reconciler._total(s) for e, s in per.items()}


def mismatches(inventory: dict[str, int], callouts: list[Callout], branches: list[Branch]) -> list[Mismatch]:
    t = step_totals(callouts, branches)
    out = [Mismatch(e, n, t.get(e, 0)) for e, n in inventory.items() if t.get(e, 0) != n]
    out += [Mismatch(e, 0, n) for e, n in t.items() if e not in inventory]
    return sorted(out, key=lambda m: -abs(m.steps - m.inventory))


class Reconciler:
    def __init__(
        self,
        inventory: dict[str, int],
        callouts: list[Callout],
        candidates: dict[str, list[tuple[float, str]]],
        multipliers: list[Multiplier],
        branches: list[Branch],
    ):
        self.inv = inventory
        self.callouts = callouts
        self.cands = candidates
        self.mults = multipliers
        self.branches = branches
        self.scopes = [scope_of(c.page, branches) for c in callouts]
        self.regions = [[i for i, m in enumerate(multipliers) if in_region(c, m)] for c in callouts]
        self.assign = {k: v[0][1] for k, v in candidates.items() if v}
        self.dist = {k: dict((e, d) for d, e in v) for k, v in candidates.items()}
        self.best = {k: v[0][0] for k, v in candidates.items() if v}

    # -- totals ---------------------------------------------------------

    def _factor(self, i: int) -> int:
        f = 1
        for r in self.regions[i]:
            if self.mults[r].applied:
                f *= self.mults[r].factor
        return f

    def _key_weights(self) -> dict[str, dict[Scope, int]]:
        out: dict[str, dict[Scope, int]] = defaultdict(lambda: defaultdict(int))
        for i, c in enumerate(self.callouts):
            out[c.image_key][self.scopes[i]] += c.count * self._factor(i)
        return out

    @staticmethod
    def _total(per_scope: dict[Scope, int]) -> int:
        shared = per_scope.get((-1, 0), 0)
        by_branch: dict[int, int] = defaultdict(int)
        for (b, _s), n in per_scope.items():
            if b >= 0:
                by_branch[b] = max(by_branch[b], n)
        return shared + sum(by_branch.values())

    def _element_scopes(self, weights) -> dict[str, dict[Scope, int]]:
        per: dict[str, dict[Scope, int]] = defaultdict(lambda: defaultdict(int))
        for key, ws in weights.items():
            e = self.assign.get(key)
            if e is None:
                continue
            for s, n in ws.items():
                per[e][s] += n
        return per

    def totals(self) -> dict[str, int]:
        per = self._element_scopes(self._key_weights())
        return {e: self._total(s) for e, s in per.items()}

    def error(self) -> int:
        t = self.totals()
        return sum(abs(t.get(e, 0) - n) for e, n in self.inv.items()) + sum(
            n for e, n in t.items() if e not in self.inv
        )

    # -- decisions --------------------------------------------------------

    def choose_multipliers(self) -> None:
        for m in self.mults:
            m.applied = False
            e_off = self.error()
            m.applied = True
            e_on = self.error()
            m.applied = e_on < e_off

    def fix_lookalikes(self, max_rounds: int = 50) -> int:
        weights = self._key_weights()
        per = self._element_scopes(weights)
        tot = {e: self._total(s) for e, s in per.items()}

        def err(e: str) -> int:
            return abs(tot.get(e, 0) - self.inv.get(e, 0))

        moves = 0
        for _ in range(max_rounds):
            best_gain, best_move = 0.0, None
            for key, ws in weights.items():
                cur = self.assign.get(key)
                if cur is None or not ws:
                    continue
                d0 = self.best[key]
                limit = max(d0 * MAX_RATIO, d0 + MIN_SLACK)
                for e2, d in self.dist[key].items():
                    if e2 == cur or d > limit:
                        continue
                    before = err(cur) + err(e2)
                    a = dict(per[cur])
                    b = dict(per.get(e2, {}))
                    for s, n in ws.items():
                        a[s] = a.get(s, 0) - n
                        b[s] = b.get(s, 0) + n
                    after = abs(self._total(a) - self.inv.get(cur, 0)) + abs(
                        self._total(b) - self.inv.get(e2, 0)
                    )
                    gain = (before - after) - DIST_WEIGHT * (d - self.dist[key][cur])
                    if gain > best_gain + 1e-9:
                        best_gain, best_move = gain, (key, cur, e2)
            if best_move is None:
                break
            key, cur, e2 = best_move
            for s, n in weights[key].items():
                per[cur][s] -= n
                per[e2][s] += n
            tot[cur] = self._total(per[cur])
            tot[e2] = self._total(per[e2])
            self.assign[key] = e2
            moves += 1
        return moves

    def run(self) -> list[Mismatch]:
        for _ in range(3):
            self.choose_multipliers()
            if self.fix_lookalikes() == 0:
                break
        self.choose_multipliers()
        for i, c in enumerate(self.callouts):
            c.element_id = self.assign.get(c.image_key)
            c.factor = self._factor(i)
            d = self.dist.get(c.image_key, {})
            if c.element_id in d:
                mine = d[c.element_id]
                others = [v for e, v in d.items() if e != c.element_id]
                second = min(others) if others else mine * 4 + 1e-6
                c.confidence = max(0.0, min(1.0, (second - mine) / (second + 1e-9)))
        return mismatches(self.inv, self.callouts, self.branches)
