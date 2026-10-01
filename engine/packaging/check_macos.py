"""Fail if any binary in a Mac build needs a newer macOS than we promise.

    python engine/packaging/check_macos.py app/dist/mac/BrickWise.app --arch x86_64 --max 12.0

Wheels built for a newer macOS install fine on the build machine and only fail
on an older Mac, when the engine won't start. This reads the minimum version
from every Mach-O file's load commands, so it runs anywhere.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

CPU = {"x86_64": 0x01000007, "arm64": 0x0100000C}
LC_VERSION_MIN_MACOSX = 0x24
LC_BUILD_VERSION = 0x32
PLATFORM_MACOS = 1
MACH_O = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe")  # 64- and 32-bit, little endian
UNIVERSAL = (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf")


def _version(v: int) -> tuple[int, int]:
    return v >> 16, (v >> 8) & 0xFF


def _slice(data: bytes, start: int) -> tuple[int, tuple[int, int] | None] | None:
    """(cputype, minimum macOS) of the Mach-O image at `start`."""
    magic = data[start : start + 4]
    if magic not in MACH_O:
        return None
    header = 32 if magic == MACH_O[0] else 28
    cputype, _, _, ncmds, _ = struct.unpack_from("<iIIII", data, start + 4)
    pos = start + header
    minos = None
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, pos)
        if cmd == LC_BUILD_VERSION:
            platform, v = struct.unpack_from("<II", data, pos + 8)
            if platform == PLATFORM_MACOS:
                minos = _version(v)
        elif cmd == LC_VERSION_MIN_MACOSX:
            minos = _version(struct.unpack_from("<I", data, pos + 8)[0])
        pos += size
    return cputype & 0xFFFFFFFF, minos


def minimums(path: str) -> list[tuple[int, tuple[int, int] | None]]:
    """(cputype, minimum macOS) for each architecture in a file; empty if it isn't Mach-O."""
    with open(path, "rb") as fh:
        head = fh.read(8)
        if head[:4] not in MACH_O + UNIVERSAL:
            return []
        data = head + fh.read()
    if data[:4] in UNIVERSAL:
        wide = data[3] == 0xBF
        (n,) = struct.unpack_from(">I", data, 4)
        if n > 30:  # a Java class file, which shares the magic number
            return []
        out = []
        for i in range(n):
            if wide:
                _, _, offset = struct.unpack_from(">iiQ", data, 8 + i * 32)
            else:
                _, _, offset = struct.unpack_from(">iiI", data, 8 + i * 20)
            image = _slice(data, offset)
            if image:
                out.append(image)
        return out
    image = _slice(data, 0)
    return [image] if image else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="an .app bundle or any folder of binaries")
    ap.add_argument("--arch", choices=sorted(CPU), required=True)
    ap.add_argument("--max", default="12.0", help="newest minimum macOS allowed (default 12.0)")
    args = ap.parse_args(argv)
    limit = tuple(int(x) for x in args.max.split("."))[:2]

    checked, newest, too_new = 0, (0, 0), []
    for root, _dirs, files in os.walk(args.path):
        for name in files:
            path = os.path.join(root, name)
            if os.path.islink(path):
                continue
            for cpu, minos in minimums(path):
                if cpu != CPU[args.arch] or minos is None:
                    continue
                checked += 1
                newest = max(newest, minos)
                if minos > limit:
                    too_new.append((minos, os.path.relpath(path, args.path)))
    if not checked:
        print(f"No {args.arch} binaries found in {args.path}", file=sys.stderr)
        return 1
    for minos, rel in sorted(too_new, reverse=True):
        print(f"needs macOS {minos[0]}.{minos[1]}: {rel}", file=sys.stderr)
    print(f"{checked} {args.arch} binaries; the newest minimum is macOS {newest[0]}.{newest[1]}")
    return 1 if too_new else 0


if __name__ == "__main__":
    sys.exit(main())
