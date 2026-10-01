"""Build the engine as a standalone program for the desktop app.

    pip install ".[package]"
    python packaging/build.py

PyInstaller writes engine/dist/brickwise-engine/: the `brickwise-engine`
executable and the libraries it needs, so the app runs without Python
installed. The app bundles that folder (see app/electron-builder.yml).
"""

import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "brickwise-engine",
        "--distpath",
        str(ENGINE / "dist"),
        "--workpath",
        str(ENGINE / "build" / "pyinstaller"),
        "--specpath",
        str(ENGINE / "build"),
        # pdfium is a native library PyInstaller can't discover from imports alone.
        "--collect-all",
        "pypdfium2_raw",
        "--collect-all",
        "pypdfium2",
        # Optional extras of the libraries above that the engine never uses.
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "PIL",
        str(ENGINE / "brickwise" / "__main__.py"),
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
