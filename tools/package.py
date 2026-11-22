#!/usr/bin/env python3
"""Build dist/lineforge-<version>.zip from addon/lineforge.

Stdlib only, so it also runs in CI on Linux/macOS:
    python3 tools/package.py
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDON = ROOT / "addon" / "lineforge"
INIT = ADDON / "__init__.py"
DIST = ROOT / "dist"
PLATFORM_TAGS = ("win64", "win-arm64", "linux-x64", "linux-arm64", "macos-arm64", "macos-x64")
BINARY_SUFFIXES = (".pyd", ".so", ".dylib")


def read_version() -> str:
    text = INIT.read_text(encoding="utf-8")
    m = re.search(r"\"version\"\s*:\s*\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)", text)
    if not m:
        raise SystemExit("could not find bl_info version in %s" % INIT)
    return "%s.%s.%s" % m.groups()


def collect_binaries() -> list[Path]:
    binaries = []
    for tag in PLATFORM_TAGS:
        folder = ADDON / "bin" / tag
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in BINARY_SUFFIXES:
                binaries.append(path)
    for path in sorted((ADDON / "bin").glob("*")):
        if path.is_file() and path.suffix.lower() in BINARY_SUFFIXES:
            binaries.append(path)  # legacy flat layout
    return binaries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", help="override the version taken from bl_info")
    ap.add_argument("--out", help="output zip path (default dist/lineforge-<version>.zip)")
    args = ap.parse_args()

    version = args.version or read_version()
    binaries = collect_binaries()
    if not binaries:
        raise SystemExit("no native core found under addon/lineforge/bin/<platform>/ — build it first")

    out = Path(args.out) if args.out else DIST / ("lineforge-%s.zip" % version)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    files: list[Path] = []
    for path in sorted(ADDON.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        files.append(path)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            zf.write(path, Path("lineforge") / path.relative_to(ADDON))
        for extra in ("README.md", "README.zh.md", "LICENSE", "CHANGELOG.md"):
            src = ROOT / extra
            if src.is_file():
                zf.write(src, Path("lineforge") / extra)

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print("packaged: %s (%d bytes)" % (out, out.stat().st_size))
    for b in binaries:
        print("  core: %s (%d bytes)" % (b.relative_to(ROOT), b.stat().st_size))
    print("sha256: %s" % digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
