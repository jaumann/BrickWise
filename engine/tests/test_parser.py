import pytest
from synthetic import Book, Step, default_book, write_book

from brickwise.cli import main, summary, where_used
from brickwise.parser import parse


@pytest.fixture(scope="module")
def book_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("books") / "book.pdf"
    write_book(str(path), default_book())
    return str(path)


@pytest.fixture(scope="module")
def parsed(book_pdf):
    return parse(book_pdf)


def test_reads_inventory(parsed):
    assert parsed.set_number == "99901"
    assert parsed.inventory_totals == default_book().inventory


def test_every_part_reconciles(parsed):
    assert parsed.mismatches == []
    assert parsed.reconciled_lines == len(default_book().inventory)


def test_finds_steps_and_bags(parsed):
    assert sorted({s.number for s in parsed.steps}) == [1, 2, 3, 4, 5, 6, 7]
    assert [b.number for b in parsed.bags] == [1, 2]


def test_repeated_sub_build_is_multiplied(parsed):
    assert len(parsed.multipliers) == 1
    m = parsed.multipliers[0]
    assert (m.factor, m.start_step, m.end_step, m.applied) == (2, 4, 5, True)
    inside = [c for c in parsed.callouts if c.step in (4, 5)]
    assert inside and all(c.factor == 2 for c in inside)


def test_where_used(parsed):
    # 4211415 is in step 2 (4x) and in the repeated step 4 (1x, built twice).
    assert [(step, n) for step, _page, n in where_used(parsed, "4211415")] == [(2, 4), (4, 2)]


def test_parts_by_bag(parsed):
    bags = parsed.parts_by_bag()
    assert bags[2] == {"302301": 3, "4119477": 2, "4211388": 2}
    assert sum(bags[1].values()) + sum(bags[2].values()) == sum(default_book().inventory.values())


def test_reports_a_mismatch(tmp_path):
    book = default_book()
    book.inventory["302301"] = 7  # one more than the steps use
    path = tmp_path / "off.pdf"
    write_book(str(path), book)
    ps = parse(str(path))
    assert [(m.element_id, m.inventory, m.steps) for m in ps.mismatches] == [("302301", 7, 6)]


def test_part_in_no_counted_step_is_reported_as_unplaced(tmp_path):
    # A part drawn only in an unlabelled panel never shows up in a parts box.
    book = default_book()
    book.pages[1] = [Step(1, [("3001021", 2), ("302301", 1)])]
    book.pages[3] = [("mult-start", 2), Step(4, [("4211388", 1)])]
    book.inventory["4211415"] = 1
    path = tmp_path / "unplaced.pdf"
    write_book(str(path), book)
    ps = parse(str(path))
    assert [(m.element_id, m.inventory, m.steps, m.unplaced) for m in ps.mismatches] == [
        ("4211415", 1, 0, True)
    ]
    assert "not in any counted step" in summary(ps)


def test_sub_build_already_totalled_is_not_multiplied(tmp_path):
    # Same layout, but the parts boxes inside the sub-build already show both copies.
    book = default_book()
    book.pages[3] = [("mult-start", 2), Step(4, [("4211388", 2), ("4211415", 2)])]
    book.pages[4] = [Step(5, [("3001021", 2)]), ("mult-end", 2)]
    path = tmp_path / "totalled.pdf"
    write_book(str(path), book)
    ps = parse(str(path))
    assert ps.mismatches == []
    assert not ps.multipliers[0].applied


def test_rejects_pdf_without_inventory(tmp_path):
    book = Book(pages=[[Step(1, [("302301", 1)])]], inventory={})
    path = tmp_path / "noinv.pdf"
    write_book(str(path), book)
    with pytest.raises(ValueError, match="no parts inventory"):
        parse(str(path))


def test_cli_parse(book_pdf, capsys):
    assert main(["parse", book_pdf]) == 0
    assert "reconciled: 5/5 parts (100.0%)" in capsys.readouterr().out
