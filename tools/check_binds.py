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
SDK_SYMBOL_TEXT = re.compile(r"_[A-Za-z0-9_$][A-Za-z0-9_$.]*")


def _unquote(text: str) -> str:
    return text.strip().strip("'\"")


def _add_tbd_value(section: str, value: str, found: set[str]) -> None:
    value = _unquote(value)
    if not value or value.startswith("["):
        return
    if section == "objc-classes":
        # A class export implies its metaclass: the linker emits both symbols from one
        # `objc-classes:` entry, so a bind to either resolves against the same library.
        name = value[len("_OBJC_CLASS_$_") :] if value.startswith("_OBJC_CLASS_$_") else value
        found.add("_OBJC_CLASS_$_" + name)
        found.add("_OBJC_METACLASS_$_" + name)
    elif section == "objc-ivars":
        found.add(value if value.startswith("_OBJC_IVAR_$_") else "_OBJC_IVAR_$_" + value)
    elif section == "objc-eh-types":
        found.add(value if value.startswith("_OBJC_EHTYPE_$_") else "_OBJC_EHTYPE_$_" + value)
    elif section.endswith("symbols"):
        found.add(value if value.startswith("_") else "_" + value)


def tbd_symbols(text: str) -> set[str]:
    """Every symbol a .tbd exports, in both of the shapes the file uses.

    Plain symbols are inline lists that wrap over many lines, so they are found with a token scan.
    objc-classes / objc-ivars / objc-eh-types hold bare names (NSAlert, NSView._frame), which the
    linker turns into `_OBJC_CLASS_$_NSAlert` and friends; those need the section parser.
    """
    found: set[str] = set(SDK_SYMBOL_TEXT.findall(text))
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            item = stripped[2:].strip()
            if re.match(r"^[a-z-]+:\s", item) or item.endswith(":"):
                section = None
                continue
            if section:
                _add_tbd_value(section, item, found)
            continue
        key, sep, rest = stripped.partition(":")
        if not sep:
            continue
        key, rest = key.strip(), rest.strip()
        if rest.startswith("[") and rest.endswith("]"):
            section = None
            for item in rest[1:-1].split(","):
                _add_tbd_value(key, item.strip(), found)
        elif rest:
            section = None
        else:
            section = key
    return found

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


MH_MAGIC_64 = 0xFEEDFACF
MH_MAGIC = 0xFEEDFACE
FAT_MAGIC_BE = 0xCAFEBABE
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_DYLD_CHAINED_FIXUPS = 0x80000034


def _thin(path: str) -> bytes:
    data = open(path, "rb").read()
    if len(data) >= 8 and struct.unpack_from(">I", data, 0)[0] == FAT_MAGIC_BE:
        count = struct.unpack_from(">I", data, 4)[0]
        for i in range(count):
            cpu, _sub, off, size, _align = struct.unpack_from(">IIIII", data, 8 + 20 * i)
            if cpu == 0x0100000C:
                return data[off : off + size]
        return b""
    return data


def _commands(data: bytes) -> list[tuple[int, int, int]]:
    magic, _cpu, _sub, _ftype, ncmds, _sz, _flags, _res = struct.unpack_from("<IIIIIIII", data, 0)
    if magic != MH_MAGIC_64:
        return []
    out = []
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        if size < 8:
            break
        out.append((off, cmd, size))
        off += size
    return out


def _cstr(data: bytes, start: int, limit: int) -> str:
    nul = data.find(b"\0", start, limit)
    if nul < 0:
        nul = limit
    return data[start:nul].decode("utf-8", "replace")


def _dylibs(data: bytes) -> list[str]:
    libs = []
    for off, cmd, size in _commands(data):
        if cmd in DYLIB_CMDS:
            name_off = struct.unpack_from("<I", data, off + 8)[0]
            libs.append(_cstr(data, off + name_off, off + size))
    return libs


def _uleb(data: bytes, i: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        b = data[i]
        i += 1
        value |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return value, i


def _sleb(data: bytes, i: int) -> int:
    _value, i = _uleb(data, i)
    return i


def _bind_stream(data: bytes, off: int, size: int, libs: list[str], out: set) -> None:
    """Walk a dyld-info bind stream and record (symbol, library) per DO_BIND."""
    if not size:
        return
    i, end = off, off + size
    ordinal = 0
    symbol = None
    while i < end:
        raw = data[i]
        op, imm = raw & 0xF0, raw & 0x0F
        i += 1
        if op == 0x00:  # DONE
            ordinal, symbol = 0, None
        elif op == 0x10:  # SET_DYLIB_ORDINAL_IMM
            ordinal = imm
        elif op == 0x20:  # SET_DYLIB_ORDINAL_ULEB
            ordinal, i = _uleb(data, i)
        elif op == 0x30:  # SET_DYLIB_SPECIAL_IMM
            ordinal = 0 if imm == 0 else (imm | 0xF0) - 0x100
        elif op == 0x40:  # SET_SYMBOL_TRAILING_FLAGS_IMM
            nul = data.find(b"\0", i, end)
            if nul < 0:
                return
            symbol = data[i:nul].decode("utf-8", "replace")
            i = nul + 1
        elif op == 0x50:  # SET_TYPE_IMM
            pass
        elif op == 0x60:  # SET_ADDEND_SLEB
            i = _sleb(data, i)
        elif op == 0x70:  # SET_SEGMENT_AND_OFFSET_ULEB
            i = _uleb(data, i)[1]
        elif op == 0x80:  # ADD_ADDR_ULEB
            i = _uleb(data, i)[1]
        elif op == 0x90:  # DO_BIND
            _emit(symbol, ordinal, libs, out)
        elif op == 0xA0:  # DO_BIND_ADD_ADDR_ULEB
            _emit(symbol, ordinal, libs, out)
            i = _uleb(data, i)[1]
        elif op == 0xB0:  # DO_BIND_ADD_ADDR_IMM_SCALED
            _emit(symbol, ordinal, libs, out)
        elif op == 0xC0:  # DO_BIND_ULEB_TIMES_SKIPPING_ULEB
            _emit(symbol, ordinal, libs, out)
            i = _uleb(data, i)[1]
            i = _uleb(data, i)[1]
        elif op == 0xD0:  # THREADED
            if imm == 0:
                i = _uleb(data, i)[1]
            # APPLY (1) has no operand
        else:
            return  # unknown opcode: refuse this image rather than report a wrong table


def _emit(symbol, ordinal: int, libs: list[str], out: set) -> None:
    if not symbol:
        return
    if 1 <= ordinal <= len(libs):
        out.add((symbol, libs[ordinal - 1]))
    else:
        out.add((symbol, "self" if ordinal == 0 else "special"))


def _chained_pairs(data: bytes, off: int, libs: list[str], out: set) -> None:
    _ver, _starts, imports_off, sym_off, count, fmt, symfmt = struct.unpack_from(
        "<IIIIIII", data, off
    )
    if symfmt != 0 or fmt not in (1, 2, 3):
        return
    width = {1: 4, 2: 8, 3: 16}[fmt]
    for i in range(count):
        p = off + imports_off + i * width
        if fmt == 3:
            value = struct.unpack_from("<Q", data, p)[0]
            ordinal, name_off = value & 0xFFFF, value >> 32
        else:
            value = struct.unpack_from("<I", data, p)[0]
            ordinal, name_off = value & 0xFF, value >> 9
        name = _cstr(data, off + sym_off + name_off, off + sym_off + name_off + 512)
        if 1 <= ordinal <= len(libs):
            out.add((name, libs[ordinal - 1]))
        else:
            out.add((name, "special"))


def binds(path: str) -> list[tuple[str, str]] | None:
    """Bound (symbol, library) pairs read straight from the image, or None if unreadable.

    This deliberately does not shell out to `dyld_info`: several Xcode versions ship a dyld_info that
    refuses these retargeted images, and silently falling back to "every import came from the
    device" is what made an earlier build reroute Studio's own Qt imports into the shim.
    """
    try:
        data = _thin(path)
    except OSError:
        return None
    if not data:
        return None
    libs = _dylibs(data)
    pairs: set[tuple[str, str]] = set()
    saw_bind_info = False
    for off, cmd, size in _commands(data):
        if cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
            saw_bind_info = True
            fields = struct.unpack_from("<10I", data, off + 8)
            for field, length in ((2, 3), (4, 5), (6, 7)):
                _bind_stream(data, fields[field], fields[length], libs, pairs)
        elif cmd == LC_DYLD_CHAINED_FIXUPS:
            saw_bind_info = True
            data_off = struct.unpack_from("<I", data, off + 8)[0]
            _chained_pairs(data, data_off, libs, pairs)
    if not saw_bind_info and libs:
        return None
    return sorted(pairs)


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
        name = m.group(1)
        # libc++.1.dylib is shipped as libc++.tbd, libSystem.B.dylib as libSystem.B.tbd.
        for candidate_name in (name, re.sub(r"\.[0-9]+$", "", name)):
            candidate = os.path.join(sdk, "usr/lib", f"{candidate_name}.tbd")
            if os.path.exists(candidate):
                return candidate
        return None
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
        with open(tbd, "r", encoding="utf-8", errors="replace") as f:
            found |= tbd_symbols(f.read())
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


def framework_reexports(app: str, sdk: str | None) -> list[str]:
    """iOS frameworks the retargeted images link, which the shim should re-export.

    Retargeting rewrites dylib ordinals in place, and several imports can share one ordinal opcode,
    so a reroute can pull a whole library's binds to the shim. Re-exporting the frameworks the images
    link is what makes those binds resolve to the real implementation rather than to a stub.
    """
    names: set[str] = set()
    for path in machos(app):
        try:
            data = _thin(path)
        except OSError:
            continue
        for library in _dylibs(data):
            m = re.match(r"^/System/Library/Frameworks/([A-Za-z0-9_]+)\.framework/", library)
            if not m or m.group(1) in ("AppKit", "Cocoa"):
                continue
            if sdk:
                tbd = os.path.join(
                    sdk, "System/Library/Frameworks", f"{m.group(1)}.framework", f"{m.group(1)}.tbd"
                )
                if not os.path.exists(tbd):
                    continue
            names.add(m.group(1))
    return sorted(names)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("app", nargs="?")
    ap.add_argument("--sdk", help="iOS SDK path, for the shim's re-exported frameworks")
    ap.add_argument(
        "--frameworks",
        action="store_true",
        help="print the iOS frameworks APP links, one per line, and exit",
    )
    args = ap.parse_args()
    if not args.app:
        ap.error("need APP")
    if args.frameworks:
        print("\n".join(framework_reexports(args.app, args.sdk)))
        return 0

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
        print(f"ERROR: {unreadable} image(s) have no readable bind information")
        return 1

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
