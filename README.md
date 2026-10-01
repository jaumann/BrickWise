# BrickWise

BrickWise reads a LEGO building instruction PDF that you own and turns it into
something you can search: which steps use a given part, which parts go in each
bag, and how far along your build is.

It runs entirely on your computer. BrickWise ships with no set data, no
instruction PDFs and no part images; everything in your library comes from
PDFs you import yourself.

> LEGO is a trademark of the LEGO Group, which does not sponsor, authorize or
> endorse this project.

## Status

Early development. The parsing engine (`engine/`) works as a command-line tool.
The desktop app (Electron) comes next.

## Repository layout

| Path | What it is |
| --- | --- |
| `engine/` | Python package that parses instruction PDFs |
| `samples/` | Your own instruction PDFs for testing. Git-ignored; never commit PDFs. |

## Trying the parser

```sh
cd engine
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
brickwise parse ../samples/6674440.pdf
```

See [engine/README.md](engine/README.md) for details.

## License

MIT, see [LICENSE](LICENSE).
