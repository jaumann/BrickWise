"""Checks against real instruction PDFs in the repo's git-ignored samples/ folder.

These run only when the PDFs are present locally. Each threshold is the share
of inventory lines whose step totals match the inventory exactly.
"""

from pathlib import Path

import pytest

from brickwise.parser import parse

SAMPLES = Path(__file__).resolve().parents[2] / "samples"

# file name: minimum share of inventory lines that reconcile
EXPECTED = {
    "6674440.pdf": 1.00,  # 40899
    "6662158.pdf": 0.98,  # 77059
    "6680505.pdf": 0.96,  # 40926, alternative builds
    "6564023.pdf": 0.91,  # 75192, minifigures drawn without counts
}


@pytest.mark.parametrize("name,minimum", sorted(EXPECTED.items()))
def test_sample_reconciles(name, minimum):
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"{name} not in samples/")
    ps = parse(str(path))
    share = ps.reconciled_lines / len(ps.inventory_totals)
    assert share >= minimum, f"{name}: {share:.1%} reconciled"
