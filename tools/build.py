#!/usr/bin/env python3
"""LineForge — cross-platform build of the native core.

The add-on targets Blender 5.2 (CPython 3.13). On Windows the easy path is build.ps1
(w64devkit, no admin rights). This script is the portable equivalent: it looks for a
C++17 compiler, the CPython 3.13 headers/libs and the pybind11 headers, then compiles
src/core.cpp + src/module.cpp into addon/lineforge/bin/<platform>/.

Usage:
    python tools/build.py                       # auto-detect everything
    python tools/build.py --cxx clang++         # pick a compiler
    python tools/build.py --python-home /opt/blender/5.2/python
    python tools/build.py --pybind11 ~/pybind11 --no-copy
    blender -b --python-expr "import sysconfig;print(sysconfig.get_paths())"   # find paths

Exit code 0 only when the module was produced; every failure prints what is missing and
how to fix it (no traceback).
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
ADDON_BIN = os.path.join(ROOT, "addon", "lineforge", "bin")
BUILD = os.path.join(ROOT, "build")

SOURCES = ["core.cpp", "module.cpp"]
PY_MINOR = "313"


def platform_tag() -> str:
    machine = (platform.machine() or "").lower()
    if sys.platform == "win32":
        return "win64" if machine in ("amd64", "x86_64", "") else "win-arm64"
    if sys.platform.startswith("linux"):
        return "linux-arm64" if machine in ("aarch64", "arm64") else "linux-x64"
    if sys.platform == "darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else "macos-x64"
    return "unknown"


def die(msg: str) -> "NoReturn":
    print("error: " + msg, file=sys.stderr)
    raise SystemExit(1)


def _python_homes(explicit: str | None) -> list[str]:
    homes: list[str] = []
    if explicit:
        homes.append(explicit)
    if os.environ.get("LINEFORGE_PYTHON"):
        homes.append(os.environ["LINEFORGE_PYTHON"])
    homes.append(os.path.join(ROOT, "toolchain", "py313", "tools"))
    if os.environ.get("BLENDER_PYTHON"):
        homes.append(os.environ["BLENDER_PYTHON"])
    homes.append(sys.base_prefix)
    try:
        import sysconfig  # noqa: PLC0415

        homes.append(sysconfig.get_paths().get("data") or "")
    except Exception:  # noqa: BLE001
        pass
    return [h for h in homes if h]


def find_python_home(explicit: str | None) -> tuple[str, str, str]:
    """Return (include_dir, lib_dir, lib_name); lib_dir/lib_name may be empty (unix)."""
    homes = _python_homes(explicit)

    include_dirs: list[str] = []
    for home in homes:
        for sub in ("include", os.path.join("include", "python" + PY_MINOR)):
            include_dirs.append(os.path.join(home, sub))
    try:
        import sysconfig  # noqa: PLC0415

        for key in ("include", "platinclude"):
            path = sysconfig.get_paths().get(key)
            if path:
                include_dirs.append(path)
        for var in ("INCLUDEPY", "CONFINCLUDEPY"):
            path = sysconfig.get_config_var(var)
            if path:
                include_dirs.append(path)
    except Exception:  # noqa: BLE001
        pass

    for inc in include_dirs:
        if not os.path.isfile(os.path.join(inc, "Python.h")):
            continue
        if sys.platform != "win32":
            # Linux/macOS extension modules leave Python symbols undefined.
            return inc, "", ""
        for home in homes:
            for lib in (os.path.join(home, "libs"), os.path.join(home, "lib"), home):
                if not os.path.isdir(lib):
                    continue
                for name in ("python" + PY_MINOR, "python3.13", "python3.13m"):
                    if os.path.isfile(os.path.join(lib, name + ".lib")):
                        return inc, lib, name
        die(
            "Python.h found in %s but python%s.lib is missing.\n"
            "  Windows needs the CPython 'libs' folder (python.org installer or the\n"
            "  python.%s nuget package); pass --python-home <root containing include+libs>."
            % (inc, PY_MINOR, PY_MINOR)
        )
    die(
        "CPython 3.13 development files not found.\n"
        "  - point --python-home at a CPython 3.13 install (Windows: the 'tools' folder\n"
        "    from the python.3.13.x nuget package, or the python.org install root), or\n"
        "  - set LINEFORGE_PYTHON to that folder."
    )


def find_pybind11(explicit: str | None) -> str:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
        candidates.append(os.path.join(explicit, "include"))
    if os.environ.get("PYBIND11_INCLUDE"):
        candidates.append(os.environ["PYBIND11_INCLUDE"])
    candidates.append(os.path.join(ROOT, "toolchain", "pybind11", "pybind11", "include"))
    candidates.append(os.path.join(ROOT, "toolchain", "pybind11", "include"))
    try:
        import pybind11  # noqa: PLC0415

        candidates.append(pybind11.get_include())
    except Exception:  # noqa: BLE001
        pass
    try:
        import sysconfig  # noqa: PLC0415

        for key in ("purelib", "platlib"):
            path = sysconfig.get_paths().get(key)
            if path:
                candidates.append(os.path.join(path, "pybind11", "include"))
    except Exception:  # noqa: BLE001
        pass
    for base in candidates:
        if base and os.path.isfile(os.path.join(base, "pybind11", "pybind11.h")):
            return base
    die(
        "pybind11 headers not found.\n"
        "  install it with 'python -m pip install pybind11', download a release and pass\n"
        "  --pybind11 <dir containing pybind11/pybind11.h>, or set PYBIND11_INCLUDE."
    )


def find_msvc() -> str | None:
    """Return vcvars64.bat for a Visual Studio install with the C++ toolset, if any."""
    if sys.platform != "win32":
        return None
    roots = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     "Microsoft Visual Studio", "Installer", "vswhere.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     "Microsoft Visual Studio", "Installer", "vswhere.exe"),
    ]
    for vswhere in roots:
        if not os.path.isfile(vswhere):
            continue
        try:
            out = subprocess.check_output(
                [vswhere, "-latest", "-products", "*",
                 "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                 "-property", "installationPath"],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            continue
        if not out:
            continue
        bat = os.path.join(out, "VC", "Auxiliary", "Build", "vcvars64.bat")
        if os.path.isfile(bat):
            return bat
    return None


def find_compiler(explicit: str | None) -> tuple[str, str]:
    """Return (kind, path); kind is 'gnu' or 'msvc'."""
    if explicit:
        if explicit.lower() in ("cl", "msvc"):
            bat = find_msvc()
            if not bat:
                die("no Visual Studio C++ toolset found (vswhere/vcvars64.bat)")
            return ("msvc", bat)
        if shutil.which(explicit) or os.path.isfile(explicit):
            return ("gnu", explicit)
        die("compiler not found: " + explicit)
    env = os.environ.get("CXX")
    if env and (shutil.which(env) or os.path.isfile(env)):
        return ("gnu", env)
    local = os.path.join(ROOT, "toolchain", "w64devkit", "w64devkit", "bin", "g++.exe")
    if os.path.isfile(local):
        return ("gnu", local)
    for name in ("g++", "clang++", "c++"):
        found = shutil.which(name)
        if found:
            return ("gnu", found)
    bat = find_msvc()
    if bat:
        return ("msvc", bat)
    die("no C++ compiler found (install g++/clang++, a Visual Studio C++ toolset, or pass --cxx)")


def run(cmd: list[str]) -> None:
    print("  $ " + " ".join(cmd))
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        die("command failed: " + " ".join(cmd))


def build_gnu(cxx: str, inc: str, pb_inc: str, obj_dir: str, out_path: str,
              lib_dir: str, lib_name: str, debug: bool) -> None:
    flags = ["-std=c++17", "-shared", "-fPIC", "-D_hypot=hypot"]
    flags += ["-O0", "-g"] if debug else ["-O2", "-DNDEBUG"]
    if sys.platform == "win32":
        flags += ["-static", "-Wl,--exclude-libs,ALL"]
    flags += ["-I" + inc, "-I" + pb_inc, "-I" + SRC]

    objs = []
    for src in SOURCES:
        path = os.path.join(SRC, src)
        if not os.path.isfile(path):
            die("missing source: " + path)
        obj = os.path.join(obj_dir, os.path.splitext(src)[0] + ".o")
        run([cxx, *flags, "-c", path, "-o", obj])
        objs.append(obj)

    link = [cxx, *flags, "-o", out_path, *objs]
    if sys.platform == "win32" and lib_dir:
        link += ["-L" + lib_dir, "-l" + lib_name]
    elif sys.platform == "darwin":
        link += ["-undefined", "dynamic_lookup"]
    run(link)


def build_msvc(vcvars: str, inc: str, pb_inc: str, out_dir: str, out_path: str,
               lib_dir: str, lib_name: str, debug: bool) -> None:
    """MSVC through vcvars64.bat: cl needs the toolset's INCLUDE/LIB environment."""
    opt = " ".join(["/Od", "/Zi"] if debug else ["/O2", "/DNDEBUG"])
    srcs = " ".join('"%s"' % os.path.join(SRC, s) for s in SOURCES)
    obj_dir = os.path.join(out_dir, "obj")
    os.makedirs(obj_dir, exist_ok=True)
    link_lib = ""
    if lib_dir and lib_name:
        link_lib = '/LIBPATH:"%s" %s.lib' % (lib_dir, lib_name)
    cmd = (
        'cl /nologo /std:c++17 /EHsc /MD /D_hypot=hypot {opt} '
        '/I"{inc}" /I"{pb}" /I"{src}" /LD {srcs} /Fe:"{out}" /Fo:"{obj}\\" '
        '/link {lib}'
    ).format(opt=opt, inc=inc, pb=pb_inc, src=SRC, srcs=srcs, out=out_path,
             obj=obj_dir, lib=link_lib)
    bat = os.path.join(out_dir, "build_msvc.bat")
    with open(bat, "w", encoding="utf-8") as fh:
        fh.write("@echo off\r\n")
        fh.write('call "%s" >nul\r\n' % vcvars)
        fh.write(cmd + "\r\n")
        fh.write("exit /b %ERRORLEVEL%\r\n")
    run(["cmd", "/c", bat])


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the LineForge native core")
    ap.add_argument("--cxx", default=None, help="C++ compiler (default: auto)")
    ap.add_argument("--python-home", default=None, help="CPython 3.13 root with include/ and libs/")
    ap.add_argument("--pybind11", default=None, help="pybind11 checkout root (contains include/)")
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--no-copy", action="store_true", help="do not copy into addon/lineforge/bin")
    ap.add_argument("--debug", action="store_true", help="-O0 -g instead of -O2 -DNDEBUG")
    args = ap.parse_args()

    tag = platform_tag()
    if tag == "unknown":
        die("unsupported platform: %s %s" % (sys.platform, platform.machine()))

    inc, lib_dir, lib_name = find_python_home(args.python_home)
    pb_inc = find_pybind11(args.pybind11)
    kind, cxx = find_compiler(args.cxx)

    obj_dir = os.path.join(BUILD, tag, "obj")
    out_dir = os.path.join(BUILD, tag)
    if args.clean:
        shutil.rmtree(os.path.join(BUILD, tag), ignore_errors=True)
    os.makedirs(obj_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    out_name = "lineforge_core.pyd" if sys.platform == "win32" else "lineforge_core.so"
    out_path = os.path.join(out_dir, out_name)

    print("== LineForge build ==")
    print("  platform : %s" % tag)
    print("  compiler : %s (%s)" % (cxx, kind))
    print("  python   : %s" % inc)
    print("  pybind11 : %s" % pb_inc)

    if kind == "msvc":
        build_msvc(cxx, inc, pb_inc, out_dir, out_path, lib_dir, lib_name, args.debug)
    else:
        build_gnu(cxx, inc, pb_inc, obj_dir, out_path, lib_dir, lib_name, args.debug)

    if not os.path.isfile(out_path):
        die("build produced no output: " + out_path)
    print("  ok: %s (%d bytes)" % (out_path, os.path.getsize(out_path)))

    if not args.no_copy:
        dest_dir = os.path.join(ADDON_BIN, tag)
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(out_path, os.path.join(dest_dir, out_name))
        print("  copied -> %s" % os.path.join(dest_dir, out_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
