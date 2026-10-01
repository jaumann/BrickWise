"""Write a synthetic instruction book, for the app's end-to-end tests.

python tests/make_book.py out.pdf            # every part adds up
python tests/make_book.py out.pdf unplaced   # one part is in no step's parts list
python tests/make_book.py out.pdf empty      # no inventory, so not a book BrickWise can read
"""

import sys

from synthetic import Book, Step, default_book, write_book


def main(path: str, variant: str = "default") -> None:
    book = default_book()
    if variant == "unplaced":
        book.pages[1] = [Step(1, [("3001021", 2), ("302301", 1)])]
        book.pages[3] = [("mult-start", 2), Step(4, [("4211388", 1)])]
        book.inventory["4211415"] = 1
    elif variant == "empty":
        book = Book(pages=[[Step(1, [("302301", 1)])]], inventory={})
    elif variant != "default":
        raise SystemExit(f"unknown variant {variant}")
    write_book(path, book)


if __name__ == "__main__":
    main(*sys.argv[1:])
