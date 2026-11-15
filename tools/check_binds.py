#!/usr/bin/env python3
"""Refuse the build unless every symbol the retargeted images want from the shim exists in it.

Retargeting points AppKit/Carbon/... at libMacShim.dylib, so dyld resolves those imports against the
shim (two-level namespace). If the shim does not export one of them, Studio dies at dlopen with
"Symbol not found" and no useful log. This check runs on the macOS runner, before the IPA is built:

  for every Mach-O in the app:  xcrun dyld_info -bind    ->  (symbol, library) pairs
  symbols bound to libMacShim.dylib  must be exported by libMacShim.dylib
  no bind may still name a macOS framework (that would mean retargeting missed a path)
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import subprocess
import sys

LC_LOAD_DYLIB = 0xC
LC_REEXPORT_DYLIB = 0x8000001F
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_LOAD_UPWARD_DYLIB = 0x80000023
DYLIB_CMDS = {LC_LOAD_DYLIB, LC_REEXPORT_DYLIB, LC_LOAD_WEAK_DYLIB, LC_LOAD_UPWARD_DYLIB}
SDK_SYMBOL = re.compile(rb"_[A-Za-z0-9_$][A-Za-z0-9_$.]*")

MACOS_FRAMEWORKS = (
    "/System/Library/Frameworks/AppKit.framework",
    "/System/Library/Frameworks/Cocoa.framework",
    "/System/Library/Frameworks/Carbon.framework",
    "/System/Library/Frameworks/ApplicationServices.framework",
    "/System/Library/Frameworks/ForceFeedback.framework",
    "/System/Library/Frameworks/DiskArbitration.framework",
    "/System/Library/Frameworks/ColorSync.framework",
    "/System/Library/Frameworks/OpenGL.framework/OpenGL",
)


def run(cmd: list[str]) -> tuple[int, str]:
    # stdin is explicitly empty and there is a deadline: a tool given no file argument would
    # otherwise read stdin, and one that gets stuck must fail the stage instead of the job.
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600
        )
    except subprocess.TimeoutExpired:
        return 124, "timeout: " + " ".join(cmd)
    return proc.returncode, proc.stdout + proc.stderr


def binds(path: str) -> list[tuple[str, str]] | None:
    """Bound (symbol, library) pairs, or None if this Xcode has no working dyld_info."""
    for tool in (["xcrun", "dyld_info", "-bind"], ["xcrun", "dyldinfo", "-bind"]):
        for arch in (["-arch", "arm64"], []):
            code, out = run(tool + arch + [path])
            if code != 0 or not out.strip():
                continue
            pairs = []
            for line in out.splitlines():
                fields = line.split()
                if len(fields) < 3 or not fields[0].startswith("0x"):
                    continue
                symbol, library = fields[1], fields[2]
                if symbol.startswith("_"):
                    pairs.append((symbol, library))
            if pairs:
                return pairs
    return None


def exports(path: str) -> set[str]:
    code, out = run(["xcrun", "nm", "-gU", "-arch", "arm64", path])
    if code != 0:
        raise SystemExit(f"nm failed on {path}")
    return {line.split()[-1] for line in out.splitlines() if line.split()}


def load_commands(path: str) -> list[tuple[int, int, int, bytes]]:
    """(cmd, cmdsize, offset, data) for a thin little-endian Mach-O; used for its re-exports."""
    with open(path, "rb") as f:
        data = f.read()
    magic, _cpu, _sub, _ftype, ncmds, _szcmds, _flags, _res = struct.unpack_from("<IIIIIIII", data, 0)
    if magic != 0xFEEDFACF:
        return []
    out = []
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        out.append((cmd, size, off, data))
        off += size
    return out


def dylib_path(entry) -> str:
    cmd, size, off, data = entry
    name_off = struct.unpack_from("<I", data, off + 8)[0]
    start = off + name_off
    end = data.index(b"\0", start, off + size)
    return data[start:end].decode("utf-8", "replace")


def tbd_for(library: str, sdk: str) -> str | None:
    m = re.match(r"^/System/Library/(?:Private)?Frameworks/([A-Za-z0-9_]+)\.framework/", library)
    if m:
        name = m.group(1)
        for prefix in ("Frameworks", "PrivateFrameworks"):
            candidate = os.path.join(sdk, "System/Library", prefix, f"{name}.framework", f"{name}.tbd")
            if os.path.exists(candidate):
                return candidate
        return None
    m = re.match(r"^/usr/lib/([A-Za-z0-9_.+]+?)(?:\.dylib)$", library)
    if m:
        candidate = os.path.join(sdk, "usr/lib", f"{m.group(1)}.tbd")
        return candidate if os.path.exists(candidate) else None
    return None


def reexported_symbols(shim: str, sdk: str) -> set[str]:
    """Symbols the shim answers through -reexport_framework (nm does not list those itself)."""
    found: set[str] = set()
    for entry in load_commands(shim):
        if entry[0] != LC_REEXPORT_DYLIB:
            continue
        library = dylib_path(entry)
        tbd = tbd_for(library, sdk)
        if not tbd:
            print(f"  warning: no .tbd for re-exported {library}")
            continue
        with open(tbd, "rb") as f:
            found.update(m.group(0).decode() for m in SDK_SYMBOL.finditer(f.read()))
    return found


def machos(root: str) -> list[str]:
    found = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            with open(path, "rb") as f:
                magic = f.read(4)
            if magic in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
                found.append(path)
    return sorted(found)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("app")
    ap.add_argument("--sdk", help="iOS SDK path, for the shim's re-exported frameworks")
    args = ap.parse_args()

    shim = os.path.join(args.app, "Frameworks", "libMacShim.dylib")
    if not os.path.exists(shim):
        raise SystemExit(f"missing {shim}")
    have = exports(shim)
    if args.sdk:
        have |= reexported_symbols(shim, args.sdk)

    images = machos(args.app)
    print(f"  {len(images)} Mach-O images, shim exports {len(have)} symbols")

    want: dict[str, list[str]] = {}
    stale: list[str] = []
    unreadable = 0
    for path in images:
        if path == shim:
            continue
        pairs = binds(path)
        if pairs is None:
            unreadable += 1
            continue
        for symbol, library in pairs:
            if os.path.basename(library) == "libMacShim.dylib":
                want.setdefault(symbol, []).append(os.path.relpath(path, args.app))
            elif library.startswith(MACOS_FRAMEWORKS):
                stale.append(f"{os.path.relpath(path, args.app)}: {symbol} -> {library}")

    if unreadable:
        print(
            f"  warning: {unreadable} image(s) could not be read with dyld_info on this Xcode; "
            "the bind check is incomplete"
        )
        if unreadable == len(images) - 1:
            print("  warning: dyld_info unavailable, skipping the bind check")
            return 0

    missing = {s: users for s, users in want.items() if s not in have}
    if stale:
        print(f"ERROR: {len(stale)} import(s) still point at a macOS framework:")
        for line in stale[:10]:
            print("  " + line)
        return 1
    if missing:
        print(f"ERROR: {len(missing)} symbol(s) bound to the shim but not exported by it:")
        for symbol, users in sorted(missing.items())[:20]:
            print(f"  {symbol} (wanted by {users[0]})")
        return 1

    print(f"  all {len(want)} shim-bound symbols resolve; no macOS framework imports left")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
