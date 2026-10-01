# BrickWise engine

Python package that reads a LEGO building instruction PDF and works out which
parts each step and bag uses. It powers the BrickWise app and also works on
its own from the command line.

## Install

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Commands

```sh
brickwise parse book.pdf [more.pdf ...]   # summary and how well step totals match the inventory
brickwise parse book.pdf --json out.json  # full result as JSON
brickwise part book.pdf 6439046           # steps that use a part
brickwise bags book.pdf                   # parts that go in each bag
brickwise import --library DIR book.pdf   # add a PDF to a library folder
brickwise serve --library DIR             # answer the desktop app over stdin/stdout
```

Example output:

```
../samples/6674440.pdf
  set 40899 · 84 pages · inventory on pages 81-82
  inventory: 112 parts, 275 pieces
  steps: 95 step numbers, 178 part pictures, 3 bags
  repeated sub-builds: 3 (1 multiplied)
  reconciled: 112/112 parts (100.0%) in 0.8s
```

## How it works

1. **Text and pictures.** [pypdfium2](https://github.com/pypdfium2-team/pypdfium2)
   reads every word with its position, and every embedded image. Part
   pictures stored as several image tiles are joined back together.
2. **Layout** (`layout.py`). Sizes are measured from the book itself: the
   small "Nx" labels under part pictures, the step numbers, the even larger
   bag numbers. From those it finds the inventory pages at the back, each
   step's parts box, bag starts, repeated sub-builds ("build this 2x", a
   start box and an end marker) and alternative builds ("go to page" jumps).
3. **Matching** (`match.py`). Each step picture is compared with every
   inventory picture after cropping to the part and putting it on a neutral
   background. Step boxes and the inventory are each drawn at one fixed
   scale per book, so once that ratio is known the drawn size of a part
   separates look-alikes such as a 1x12 and a 1x16 plate.
4. **Reconciling** (`reconcile.py`). Step counts are added up per part and
   compared with the inventory. That comparison decides whether a repeated
   sub-build's parts boxes show one copy or the total, takes the larger
   branch for alternative builds, and moves a picture to its runner-up match
   when that makes the totals agree and the runner-up is nearly as close.
   Whatever still disagrees is reported as a mismatch for the user to settle.

## Library

`library.py` keeps the user's imported sets in one folder: a SQLite database
(inventory, steps, bags and every part picture's step and count) and PNGs of
the part pictures, cut from the PDF with their background made transparent.
It also records what the user changes while checking parts: a step picture
matched to a different part, a piece placed in a bag or step by hand (1x
each), or a count left as it is. Totals and per-bag lists are worked out from
those records each time, using the same reconciliation code as the parser.

`server.py` is how the desktop app reaches the library: one JSON request per
line on stdin, one reply per line on stdout. Imports run one at a time in a
child process, so a crash or a cancel never takes the server down.
`packaging/build.py` freezes the engine with PyInstaller for the app.

## Tests

```sh
pytest
```

`tests/synthetic.py` draws small fake instruction books, so the tests need no
LEGO PDFs. `tests/test_samples.py` also checks real books if you put them in
the repository's git-ignored `samples/` folder; current results:

| Set | Pages | Parts reconciled | Notes |
| --- | --- | --- | --- |
| 40899 | 84 | 112/112 (100%) | |
| 77059 | 120 | 163/165 (99%) | |
| 40926 | 120 | 144/149 (97%) | alternative builds |
| 75192 | 496 | 644/702 (92%) | 35 of the 58 misses are minifigure parts this 2017 book draws without counts |
