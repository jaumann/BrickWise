import shutil

import make_book
import numpy as np
import pytest
from synthetic import default_book, part_pixels, write_book

from brickwise.library import Library, LibraryError, cut_out


@pytest.fixture(scope="module")
def book_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("books") / "book.pdf"
    write_book(str(path), default_book())
    return str(path)


@pytest.fixture(scope="module")
def unplaced_pdf(tmp_path_factory):
    # 4211415 is only drawn in an unlabelled panel, so no step counts it.
    path = tmp_path_factory.mktemp("books") / "unplaced.pdf"
    make_book.main(str(path), "unplaced")
    return str(path)


@pytest.fixture
def lib(tmp_path):
    lib = Library(tmp_path / "library")
    yield lib
    lib.close()


def picture_of(lib, set_id, element_id):
    row = lib.db.execute(
        "SELECT picture FROM callouts WHERE set_id = ? AND element_id = ?", (set_id, element_id)
    ).fetchone()
    return f"sets/{set_id}/pictures/{row[0]}"


def test_import_adds_a_set_with_its_pictures(lib, book_pdf):
    set_id, new = lib.import_pdf(book_pdf)
    assert new
    [s] = lib.list_sets()
    assert (s["id"], s["set_number"], s["name"]) == (set_id, "99901", "Set 99901")
    assert (s["parts"], s["pieces"], s["bags"], s["reconciled"], s["to_check"]) == (5, 23, 2, 5, 0)
    assert (lib.root / s["cover"]).is_file()

    detail = lib.get_set(set_id)
    assert [b["number"] for b in detail["bag_list"]] == [1, 2]
    for item in detail["inventory"]:
        assert (lib.root / item["picture"]).is_file()
        assert item["status"] == "ok"
    bags = {i["element_id"]: (dict(i["bags"]), i["no_bag"]) for i in detail["inventory"]}
    assert bags["302301"] == ({1: 3, 2: 3}, 0)
    assert bags["4211415"] == ({1: 6}, 0)
    assert not list((lib.root / "sets").glob(".importing-*"))


def test_same_pdf_is_only_imported_once(lib, book_pdf):
    first, _ = lib.import_pdf(book_pdf)
    assert lib.import_pdf(book_pdf) == (first, False)
    assert len(lib.list_sets()) == 1


def test_library_is_kept_between_sessions(tmp_path, book_pdf):
    lib = Library(tmp_path / "library")
    lib.import_pdf(book_pdf)
    lib.close()
    again = Library(tmp_path / "library")
    assert [s["set_number"] for s in again.list_sets()] == ["99901"]
    again.close()


def test_failed_import_leaves_nothing_behind(lib, tmp_path):
    bad = tmp_path / "not-a-book.pdf"
    bad.write_bytes(b"%PDF-1.4 nonsense")
    with pytest.raises(Exception):  # noqa: B017 - whatever pdfium raises
        lib.import_pdf(str(bad))
    assert lib.list_sets() == []
    assert not list((lib.root / "sets").iterdir())


def test_unplaced_part_can_be_placed_in_a_bag_or_step(lib, unplaced_pdf):
    set_id, _ = lib.import_pdf(unplaced_pdf)
    assert lib.list_sets()[0]["to_check"] == 1
    [item] = lib.review(set_id)["items"]
    assert (item["element_id"], item["inventory"], item["steps"], item["unplaced"]) == ("4211415", 1, 0, True)

    review = lib.place(set_id, "4211415", bag=2)
    [item] = review["items"]
    assert item["ok"] and item["steps"] == 1
    assert [(p["bag"], p["step"]) for p in item["placed"]] == [(2, None)]
    assert review["set"]["to_check"] == 0
    parts = {i["element_id"]: dict(i["bags"]) for i in lib.get_set(set_id)["inventory"]}
    assert parts["4211415"] == {2: 1}

    review = lib.unplace(set_id, item["placed"][0]["id"])
    [item] = review["items"]
    assert item["unplaced"] and not item["ok"]

    step7 = next(s for s in review["steps"] if s["number"] == 7)
    [item] = lib.place(set_id, "4211415", step_id=step7["id"])["items"]
    assert [(p["bag"], p["step"]) for p in item["placed"]] == [(2, 7)]


def test_reassigning_a_picture_moves_every_step_that_uses_it(lib, book_pdf):
    set_id, _ = lib.import_pdf(book_pdf)
    plate = picture_of(lib, set_id, "302301")

    items = {i["element_id"]: i for i in lib.reassign(set_id, plate, "4211388")["items"]}
    assert (items["302301"]["inventory"], items["302301"]["steps"]) == (6, 0)
    assert (items["4211388"]["inventory"], items["4211388"]["steps"]) == (4, 10)
    [group] = [g for g in items["4211388"]["groups"] if g["edited"]]
    assert sorted(u["step"] for u in group["uses"]) == [1, 3, 6]
    assert "302301" in [c["element_id"] for c in group["candidates"]]
    # The part that came up short offers that picture as a likely look-alike.
    suspects = {(g["picture"], g["matched_to"]) for g in items["302301"]["suspects"]}
    assert (plate, "4211388") in suspects

    review = lib.reassign(set_id, plate, "302301")
    assert all(i["ok"] for i in review["items"])
    assert review["set"]["to_check"] == 0


def test_reassign_only_to_parts_in_the_inventory(lib, book_pdf):
    set_id, _ = lib.import_pdf(book_pdf)
    with pytest.raises(LibraryError, match="not in this set's inventory"):
        lib.reassign(set_id, picture_of(lib, set_id, "302301"), "9999999")


def test_accepting_a_disagreement(lib, unplaced_pdf):
    set_id, _ = lib.import_pdf(unplaced_pdf)
    review = lib.accept(set_id, "4211415")
    assert review["items"][0]["accepted"]
    assert review["set"]["to_check"] == 0
    assert lib.get_set(set_id)["inventory"][2]["status"] == "accepted"
    review = lib.accept(set_id, "4211415", accepted=False)
    assert review["set"]["to_check"] == 1
    assert lib.accept(set_id)["set"]["to_check"] == 0


def test_page_images_are_rendered_and_cached(lib, book_pdf, tmp_path):
    pdf = tmp_path / "moved.pdf"
    shutil.copy(book_pdf, pdf)
    set_id, _ = lib.import_pdf(str(pdf))
    page = lib.page_image(set_id, 2)
    assert (lib.root / page["path"]).is_file()
    assert (round(page["width"]), round(page["height"]), page["page_count"]) == (420, 300, 9)
    with pytest.raises(LibraryError, match="no page 99"):
        lib.page_image(set_id, 99)

    pdf.unlink()
    assert lib.page_image(set_id, 2) == page  # cached
    assert not lib.list_sets()[0]["pdf_found"]
    with pytest.raises(LibraryError, match="no longer at"):
        lib.page_image(set_id, 3)


def test_rename_and_delete(lib, book_pdf):
    set_id, _ = lib.import_pdf(book_pdf)
    assert lib.rename(set_id, "  Tiny test set ")["name"] == "Tiny test set"
    with pytest.raises(LibraryError):
        lib.rename(set_id, " ")
    lib.delete(set_id)
    assert lib.list_sets() == []
    assert not lib.set_dir(set_id).exists()
    with pytest.raises(LibraryError, match="no longer in the library"):
        lib.get_set(set_id)


def test_picture_background_is_cut_out():
    rgb = part_pixels("4211415", 1.0)
    bgra = cut_out(rgb)
    h, w = bgra.shape[:2]
    assert bgra.shape[2] == 4
    assert bgra[0, 0, 3] == 0 and bgra[h - 1, w - 1, 3] == 0
    assert bgra[h // 2, w // 2, 3] == 255
    # A picture without a plain border is kept as it is.
    noisy = np.random.default_rng(1).integers(0, 255, (20, 30, 3), dtype=np.uint8)
    assert cut_out(noisy).shape == (20, 30, 3)
