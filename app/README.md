# BrickWise app

The desktop app: an Electron window with a React interface, over the Python
engine in `../engine`. The engine runs as a separate process that the app
talks to over stdin and stdout (see `engine/brickwise/server.py`), and it owns
the library: a SQLite database plus pictures cut from the PDFs you import.

## Installing a Mac build

Each run of the `app` workflow in GitHub Actions builds two `.dmg` files:
`BrickWise-mac-apple-silicon` for M-series Macs and `BrickWise-mac-intel` for
Intel Macs. Both need macOS 13 Ventura or later (Electron 44's minimum).

The app is not yet signed with an Apple Developer ID, so macOS blocks it the
first time. Either:

- open it once, then go to System Settings › Privacy & Security and choose
  **Open Anyway**, or
- after copying it to Applications, run
  `xattr -dr com.apple.quarantine /Applications/BrickWise.app`.

Your library lives in `~/Library/Application Support/BrickWise/library`.
Removing the app leaves it in place.

## Running from source

You need Node 22 and Python 3.10 or newer.

```sh
cd engine
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd ../app
npm install
npm run dev
```

In development the app runs the engine with `engine/.venv/bin/python` if it
exists, otherwise `python3`; set `BRICKWISE_PYTHON` to use another. Set
`BRICKWISE_LIBRARY` to keep a separate library folder while testing.

## Checks

```sh
npm run typecheck
npm run build && npm test    # end-to-end tests: real app, real engine, synthetic books
```

The end-to-end tests draw small fake instruction books with
`engine/tests/make_book.py`, so they need no LEGO PDFs. On Linux, run them
under `xvfb-run`.

## Packaging

```sh
pip install -e "../engine[package]"
npm run engine               # PyInstaller: engine/dist/brickwise-engine
npm run package -- --mac --arm64   # electron-builder: dist/BrickWise-<version>-arm64.dmg
npm run package -- --mac --x64     # an Intel build, on an Intel Mac
```

Build each architecture on a Mac of that kind, because the engine is built
with the Python that runs it. pip also picks wheels made for the Mac it runs
on, which can need a newer macOS than the app does; CI downloads wheels for
macOS 13 first and then checks every binary in the app with
`engine/packaging/check_macos.py`.

`npm run package` bundles the PyInstaller output inside the app, so the
packaged app needs no Python. To test a packaged build, point the end-to-end
tests at its executable with `BRICKWISE_APP`.

## Layout

| Path                | What it is                                                             |
| ------------------- | ---------------------------------------------------------------------- |
| `src/main/`         | Electron main process: window, engine process, `brickwise://` pictures |
| `src/preload/`      | The small API the window gets as `window.brickwise`                    |
| `src/renderer/`     | The interface: library, set view, check parts                          |
| `src/shared/api.ts` | Types for what the engine sends back                                   |
| `tests/`            | Playwright end-to-end tests                                            |
