#!/usr/bin/env python3
"""Retarget an arm64 macOS Mach-O so the iOS dyld will load it.

Studio's engine and its Qt 5.15 frameworks are ordinary Apple Silicon macOS binaries. iOS runs the
same arm64 instructions, so what stands between them and an iPad is the Mach-O header:

  * `LC_BUILD_VERSION` says macOS(1); dyld on iOS refuses that image.
  * Dependency paths use the macOS versioned layout (`X.framework/Versions/A/X`).
  * AppKit, Carbon, ApplicationServices and friends do not exist on iOS.
  * The main executable is `MH_EXECUTE`, which dyld will not `dlopen`.

One file per run, written to a new path (the input is never modified):

  platform     macOS -> iOS, minos/sdk set
  paths        Qt framework bundles -> @rpath/libQtX.dylib (the build ships them flat)
               /X.framework/Versions/A/X -> /X.framework/X
               @executable_path/../Frameworks/... -> @rpath/...
               @executable_path/../Frameworks / @loader_path/../Frameworks rpath -> @executable_path/Frameworks
  shim         frameworks with no iOS equivalent -> @rpath/libMacShim.dylib
  execute      MH_EXECUTE -> MH_DYLIB (`__PAGEZERO`'s load command becomes `LC_ID_DYLIB`, `LC_MAIN`
               stays so the host can call it, MH_PIE cleared), as LiveContainer does
  duplicates   several macOS frameworks map to the same shim path: keep the first load command and
               renumber the import ordinals so every bind still reaches the right library
  --reroute    imports listed in FILE bind to libMacShim instead of the library the macOS binary
               attributed them to (two-level namespace: a shim stub only satisfies an import whose
               ordinal names the shim)

The old code signature is left in place; it is invalid after this and the build re-signs ad-hoc.
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import sys

MH_MAGIC_64 = 0xFEEDFACF
MH_EXECUTE = 2
MH_DYLIB = 6
MH_PIE = 0x200000

LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_LOAD_DYLIB = 0xC
LC_ID_DYLIB = 0xD
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_REEXPORT_DYLIB = 0x8000001F
LC_LOAD_UPWARD_DYLIB = 0x80000023
LC_RPATH = 0x8000001C
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_BUILD_VERSION = 0x32
LC_VERSION_MIN_MACOSX = 0x24
LC_DYLD_CHAINED_FIXUPS = 0x80000034

DYLIB_CMDS = {LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LOAD_UPWARD_DYLIB}

PLATFORM_MACOS = 1
PLATFORM_IOS = 2

SHIM = "@rpath/libMacShim.dylib"

# Frameworks whose macOS API surface is not on iOS: their load commands go to the shim, which
# re-exports the iOS frameworks Studio also needs (Foundation, UIKit, CoreGraphics, ...).
SHIM_FRAMEWORKS = {
    "AppKit",
    "Cocoa",
    "ApplicationServices",
    "Carbon",
    "ForceFeedback",
    "DiskArbitration",
    "ColorSync",
    "IOKit",
    "OpenGL",
}
# dylibs that are not part of iOS (the shim provides offline/no-op versions)
SHIM_DYLIBS = {"/usr/lib/libcups.2.dylib", "/usr/lib/libcups.dylib"}

FW_PREFIX = "/System/Library/Frameworks/"
PRIVATE_FW_PREFIX = "/System/Library/PrivateFrameworks/"
QT_FRAMEWORK = re.compile(
    r"^@rpath/(Qt[A-Za-z0-9]*)\.framework(?:/Versions/[A-Za-z0-9_.]+)?(?:/(?:Qt[A-Za-z0-9]*))?$"
)

MACOS_FW = re.compile(
    r"^(/System/Library/(?:Private)?Frameworks)/([A-Za-z0-9_]+)\.framework/Versions/[A-Za-z0-9_.]+/([A-Za-z0-9_]+)$"
)
MACOS_FW_FLAT = re.compile(
    r"^(/System/Library/(?:Private)?Frameworks)/([A-Za-z0-9_]+)\.framework/([A-Za-z0-9_]+)$"
)


def note(msg: str) -> None:
    print("  " + msg)


def version_code(text: str) -> int:
    parts = [int(x) for x in text.split(".")]
    parts += [0, 0, 0]
    return (parts[0] << 16) | (parts[1] << 8) | parts[2]


def thin_arm64(path: str) -> bytearray:
    data = open(path, "rb").read()
    if struct.unpack_from(">I", data, 0)[0] != 0xCAFEBABE:
        return bytearray(data)
    count = struct.unpack_from(">I", data, 4)[0]
    for i in range(count):
        cpu, sub, off, size, _align = struct.unpack_from(">IIIII", data, 8 + 20 * i)
        if cpu == 0x0100000C and (sub & 0xFFFFFF) == 0:
            return bytearray(data[off : off + size])
    raise SystemExit(f"{path}: universal file with no arm64 slice")


def header(data: bytearray) -> dict:
    magic, cpu, sub, ftype, ncmds, szcmds, flags, _res = struct.unpack_from("<IIIIIIII", data, 0)
    if magic != MH_MAGIC_64:
        raise SystemExit(f"not a thin 64-bit little-endian Mach-O (magic {magic:#x})")
    if cpu != 0x0100000C:
        raise SystemExit(f"not arm64 (cputype {cpu:#x})")
    return dict(ftype=ftype, ncmds=ncmds, szcmds=szcmds, flags=flags)


def commands(data: bytearray) -> list[tuple[int, int, int]]:
    h = header(data)
    out = []
    off = 32
    for _ in range(h["ncmds"]):
        cmd, size = struct.unpack_from("<II", data, off)
        if size < 8 or off + size > 32 + h["szcmds"]:
            raise SystemExit(f"bad load command {cmd:#x} at {off}")
        out.append((off, cmd, size))
        off += size
    return out


def cstr(data: bytearray, start: int, end: int) -> str:
    nul = data.find(b"\0", start, end)
    if nul < 0:
        raise SystemExit(f"unterminated string at {start}")
    return bytes(data[start:nul]).decode("utf-8", "replace")


def dylib_name(data: bytearray, off: int, size: int) -> tuple[int, str]:
    name_off = struct.unpack_from("<I", data, off + 8)[0]
    return name_off, cstr(data, off + name_off, off + size)


def set_string(data: bytearray, off: int, size: int, name_off: int, new: str) -> None:
    enc = new.encode() + b"\0"
    capacity = size - name_off
    if len(enc) > capacity:
        raise SystemExit(f"replacement path does not fit: {new!r} ({len(enc)} > {capacity} bytes)")
    data[off + name_off : off + size] = enc + b"\0" * (capacity - len(enc))


def map_install_name(path: str) -> str | None:
    """The iOS name for a macOS dependency path, or None to leave it alone."""
    original = path
    if path.startswith("@executable_path/../Frameworks/"):
        path = "@rpath/" + path[len("@executable_path/../Frameworks/") :]
    m = QT_FRAMEWORK.match(path)
    if m:
        return f"@rpath/lib{m.group(1)}.dylib"
    m = MACOS_FW.match(path)
    if m:
        _prefix, name, leaf = m.groups()
        if name in SHIM_FRAMEWORKS:
            return SHIM
        return f"{FW_PREFIX}{name}.framework/{name}"
    m = MACOS_FW_FLAT.match(path)
    if m:
        _prefix, name, _leaf = m.groups()
        if name in SHIM_FRAMEWORKS:
            return SHIM
        return f"{FW_PREFIX}{name}.framework/{name}"
    if path in SHIM_DYLIBS:
        return SHIM
    if path != original:
        return path
    return None


def map_rpath(path: str) -> str | None:
    if path in ("@executable_path/../Frameworks", "@loader_path/../Frameworks"):
        return "@executable_path/Frameworks"
    return None


def rewrite_paths(data: bytearray) -> list[str]:
    log = []
    for off, cmd, size in commands(data):
        if cmd in DYLIB_CMDS or cmd == LC_ID_DYLIB:
            name_off, old = dylib_name(data, off, size)
            new = map_install_name(old)
            if new and new != old:
                set_string(data, off, size, name_off, new)
                log.append(f"{old} -> {new}")
        elif cmd == LC_RPATH:
            name_off, old = dylib_name(data, off, size)
            new = map_rpath(old)
            if new:
                set_string(data, off, size, name_off, new)
                log.append(f"rpath {old} -> {new}")
    return log


def set_platform(data: bytearray, minos: str, sdk: str) -> list[str]:
    log = []
    seen = False
    for off, cmd, size in commands(data):
        if cmd == LC_VERSION_MIN_MACOSX:
            raise SystemExit("legacy LC_VERSION_MIN_MACOSX binary: unsupported")
        if cmd == LC_BUILD_VERSION:
            seen = True
            platform = struct.unpack_from("<I", data, off + 8)[0]
            if platform == PLATFORM_MACOS:
                struct.pack_into(
                    "<III", data, off + 8, PLATFORM_IOS, version_code(minos), version_code(sdk)
                )
                log.append(f"build_version macOS -> iOS (minos {minos}, sdk {sdk})")
    if not seen:
        raise SystemExit("no LC_BUILD_VERSION: not a modern macOS binary")
    return log


def make_loadable(data: bytearray) -> list[str]:
    """MH_EXECUTE -> MH_DYLIB so dyld will dlopen it; LC_MAIN is kept for the host."""
    h = header(data)
    if h["ftype"] != MH_EXECUTE:
        return ["already a dylib/bundle; filetype kept"]

    pagezero = pagezero_size = None
    for off, cmd, size in commands(data):
        if cmd == LC_SEGMENT_64 and cstr(data, off + 8, off + 24) == "__PAGEZERO":
            pagezero, pagezero_size = off, size
    if pagezero is None:
        raise SystemExit("executable has no __PAGEZERO segment")

    vmaddr, vmsize = struct.unpack_from("<QQ", data, pagezero + 24)
    if vmsize:
        struct.pack_into("<QQ", data, pagezero + 24, vmaddr, 0x4000)

    # The segment's load command becomes LC_ID_DYLIB in place: no room is needed after the load
    # commands, and a segment index is only load-bearing for chained fixups, which Studio's main
    # executable does not use.
    for off, cmd, size in commands(data):
        if cmd == LC_DYLD_CHAINED_FIXUPS:
            raise SystemExit(
                "executable uses chained fixups: converting __PAGEZERO would renumber its segments"
            )

    name = b"@rpath/StudioKit.dylib\0"
    needed = 24 + len(name)
    if needed > pagezero_size:
        raise SystemExit(
            f"__PAGEZERO's load command is too small for LC_ID_DYLIB ({pagezero_size} < {needed})"
        )
    data[pagezero : pagezero + pagezero_size] = (
        struct.pack("<IIIIII", LC_ID_DYLIB, pagezero_size, 24, 2, 0x10000, 0x10000)
        + name
        + b"\0" * (pagezero_size - needed)
    )

    struct.pack_into("<I", data, 12, MH_DYLIB)
    struct.pack_into("<I", data, 24, h["flags"] & ~MH_PIE)
    return ["MH_EXECUTE -> MH_DYLIB (__PAGEZERO one page, LC_ID_DYLIB, LC_MAIN kept, PIE off)"]


def _uleb(data: bytearray, i: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        b = data[i]
        i += 1
        value |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return value, i


def _skip_uleb(data: bytearray, i: int) -> int:
    while data[i] & 0x80:
        i += 1
    return i + 1


def remap_binds(data: bytearray, off: int, size: int, remap: dict[int, int], which: str) -> int:
    """Renumber dylib ordinals in a dyld-info stream (ordinals only ever shrink)."""
    if not size:
        return 0
    i, end, changed = off, off + size, 0
    while i < end:
        raw = data[i]
        op, imm = raw & 0xF0, raw & 0x0F
        i += 1
        if op == 0x10:
            if imm in remap:
                data[i - 1] = 0x10 | remap[imm]
                changed += 1
        elif op == 0x20:
            value, j = _uleb(data, i)
            if value in remap:
                new = remap[value]
                width = j - i
                enc = bytearray()
                while True:
                    b = new & 0x7F
                    new >>= 7
                    enc.append(b | (0x80 if new else 0))
                    if not new:
                        break
                if len(enc) != width:
                    raise SystemExit(
                        f"{which}: ordinal {value}->{new} needs {len(enc)} bytes, stream has {width}"
                    )
                data[i:j] = enc
                changed += 1
            i = j
        elif op in (0x00, 0x30, 0x50, 0x90, 0xB0):
            continue
        elif op in (0x40,):
            nul = data.find(b"\0", i, end)
            if nul < 0:
                raise SystemExit(f"{which}: unterminated bind symbol")
            i = nul + 1
        elif op in (0x60, 0x70, 0x80, 0xA0):
            i = _skip_uleb(data, i)
        elif op == 0xC0:
            i = _skip_uleb(data, _skip_uleb(data, i))
        elif op == 0xF0:
            if imm == 0:
                i = _skip_uleb(data, i)
        else:
            raise SystemExit(f"{which}: unsupported bind opcode {raw:#x} at {i - 1}")
    return changed


def remap_chained(data: bytearray, off: int, size: int, remap: dict[int, int], which: str) -> int:
    _ver, _starts, imports_off, _sym_off, count, fmt, symfmt = struct.unpack_from(
        "<IIIIIII", data, off
    )
    if symfmt != 0 or fmt not in (1, 2, 3):
        return 0
    width = {1: 4, 2: 8, 3: 16}[fmt]
    changed = 0
    for i in range(count):
        p = off + imports_off + i * width
        if fmt == 3:
            value = struct.unpack_from("<Q", data, p)[0]
            lib = value & 0xFFFF
            if lib in remap:
                struct.pack_into("<Q", data, p, (value & ~0xFFFF) | remap[lib])
                changed += 1
        else:
            value = struct.unpack_from("<I", data, p)[0]
            lib = value & 0xFF
            if lib in remap:
                struct.pack_into("<I", data, p, (value & ~0xFF) | remap[lib])
                changed += 1
    return changed


def remap_symtab(data: bytearray, remap: dict[int, int]) -> None:
    for off, cmd, _size in commands(data):
        if cmd != LC_SYMTAB:
            continue
        symoff, nsyms = struct.unpack_from("<II", data, off + 8)
        for i in range(nsyms):
            entry = symoff + 16 * i
            ntype = data[entry + 4]
            if ntype & 0xE0 or (ntype & 0x0E) != 0:
                continue  # stab or defined symbol
            desc = struct.unpack_from("<H", data, entry + 6)[0]
            lib = desc >> 8
            if lib in remap:
                struct.pack_into("<H", data, entry + 6, (desc & 0xFF) | (remap[lib] << 8))


def dedupe_dylibs(data: bytearray) -> list[str]:
    commands_now = [(off, cmd, size) for off, cmd, size in commands(data) if cmd in DYLIB_CMDS]
    first: dict[str, int] = {}
    remap: dict[int, int] = {}
    drop: set[int] = set()
    for ordinal, (off, cmd, size) in enumerate(commands_now, 1):
        path = dylib_name(data, off, size)[1]
        if path in first:
            keep = first[path]
            drop.add(off)
            if cmd != LC_LOAD_WEAK_DYLIB and commands_now[keep - 1][1] == LC_LOAD_WEAK_DYLIB:
                struct.pack_into("<I", data, commands_now[keep - 1][0], LC_LOAD_DYLIB)
            remap[ordinal] = remap[keep]
        else:
            first[path] = ordinal
            remap[ordinal] = len(first)
    if not drop:
        return []
    if max(remap.values()) > 253:
        raise SystemExit("too many dylibs to renumber")

    for off, cmd, size in commands(data):
        if cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
            fields = struct.unpack_from("<8I", data, off + 8)
            remap_binds(data, fields[2], fields[3], remap, "bind")
            remap_binds(data, fields[6], fields[7], remap, "lazy bind")
        elif cmd == LC_DYLD_CHAINED_FIXUPS:
            data_off = struct.unpack_from("<I", data, off + 8)[0]
            remap_chained(data, data_off, size, remap, "chained imports")
    remap_symtab(data, remap)

    h = header(data)
    kept = b"".join(bytes(data[off : off + size]) for off, _cmd, size in commands(data) if off not in drop)
    base = 32
    data[base : base + h["szcmds"]] = kept + b"\0" * (h["szcmds"] - len(kept))
    struct.pack_into("<II", data, 16, h["ncmds"] - len(drop), len(kept))
    return [f"removed {len(drop)} duplicate dylib load command(s), import ordinals renumbered"]


def shim_ordinal(data: bytearray) -> int | None:
    ordinal = None
    index = 0
    for off, cmd, size in commands(data):
        if cmd in DYLIB_CMDS:
            index += 1
            if dylib_name(data, off, size)[1] == SHIM:
                ordinal = index
    return ordinal


def reroute(data: bytearray, names: set[str]) -> list[str]:
    """Point the named imports at the shim (two-level namespace)."""
    if not names:
        return []
    ordinal = shim_ordinal(data)
    if ordinal is None:
        return ["no libMacShim reference: nothing to reroute"]

    done: set[str] = set()
    no_slot = 0  # binds whose ordinal opcode had no room; counted, not fatal
    for off, cmd, size in commands(data):
        if cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
            fields = struct.unpack_from("<8I", data, off + 8)
            for start, length in ((fields[2], fields[3]), (fields[6], fields[7])):
                done |= reroute_binds(data, start, length, names, ordinal)
        elif cmd == LC_DYLD_CHAINED_FIXUPS:
            data_off = struct.unpack_from("<I", data, off + 8)[0]
            done |= reroute_chained(data, data_off, names, ordinal)
        elif cmd == LC_SYMTAB:
            done |= reroute_symtab(data, off, names, ordinal)

    log = [f"rerouted {len(done)} of {len(names)} planned import(s) (shim ordinal {ordinal})"]
    if no_slot:
        log.append(f"{no_slot} bind(s) had no ordinal opcode to rewrite")
    return log


def _set_ordinal(data: bytearray, kind: str, pos: int, value: int) -> bool:
    """Write `value` into an ordinal opcode in place, keeping its encoding width."""
    if kind == "imm":
        if value > 15:
            return False
        data[pos] = 0x10 | value
        return True
    old, j = _uleb(data, pos)
    width = j - pos
    enc = bytearray()
    v = value
    while True:
        b = v & 0x7F
        v >>= 7
        enc.append(b | (0x80 if v else 0))
        if not v:
            break
    if len(enc) != width:
        return False
    data[pos:j] = enc
    return True


def reroute_binds(
    data: bytearray, off: int, size: int, names: set[str], ordinal: int
) -> set[str]:
    if not size:
        return set()
    done: set[str] = set()
    i, end = off, off + size
    pending: tuple[str, int] | None = None
    while i < end:
        raw = data[i]
        op, imm = raw & 0xF0, raw & 0x0F
        i += 1
        if op == 0x10:
            pending = ("imm", i - 1)
        elif op == 0x20:
            pending = ("uleb", i)
            i = _skip_uleb(data, i)
        elif op == 0x40:
            nul = data.find(b"\0", i, end)
            name = bytes(data[i:nul]).decode("utf-8", "replace")
            if name in names and pending is not None:
                if _set_ordinal(data, pending[0], pending[1], ordinal):
                    done.add(name)
                else:
                    raise SystemExit(f"{name}: ordinal opcode has no room for the shim ordinal")
            i = nul + 1
        elif op in (0x00, 0x30, 0x50, 0x90, 0xB0):
            continue
        elif op in (0x60, 0x70, 0x80, 0xA0):
            i = _skip_uleb(data, i)
        elif op == 0xC0:
            i = _skip_uleb(data, _skip_uleb(data, i))
        elif op == 0xF0:
            if imm == 0:
                i = _skip_uleb(data, i)
        else:
            raise SystemExit(f"unsupported bind opcode {raw:#x} at {i - 1}")
    return done


def reroute_chained(data: bytearray, off: int, names: set[str], ordinal: int) -> set[str]:
    _ver, _starts, imports_off, sym_off, count, fmt, symfmt = struct.unpack_from(
        "<IIIIIII", data, off
    )
    if symfmt != 0 or fmt not in (1, 2, 3):
        return set()
    width = {1: 4, 2: 8, 3: 16}[fmt]
    done: set[str] = set()
    for i in range(count):
        p = off + imports_off + i * width
        if fmt == 3:
            value = struct.unpack_from("<Q", data, p)[0]
            name_off = value >> 32
        else:
            value = struct.unpack_from("<I", data, p)[0]
            name_off = value >> 9
        name = cstr(data, off + sym_off + name_off, off + sym_off + name_off + 256)
        if name not in names:
            continue
        if fmt == 3:
            struct.pack_into("<Q", data, p, (value & ~0xFFFF) | ordinal)
        else:
            if ordinal > 0xFF:
                raise SystemExit("shim ordinal too large for a chained-fixups import")
            struct.pack_into("<I", data, p, (value & ~0xFF) | ordinal)
        done.add(name)
    return done


def reroute_symtab(data: bytearray, off: int, names: set[str], ordinal: int) -> set[str]:
    symoff, nsyms = struct.unpack_from("<II", data, off + 8)
    strsize_off = off + 16 + 4
    stroff = struct.unpack_from("<I", data, strsize_off)[0]
    done: set[str] = set()
    for i in range(nsyms):
        entry = symoff + 16 * i
        strx = struct.unpack_from("<I", data, entry)[0]
        ntype = data[entry + 4]
        if ntype & 0xE0 or (ntype & 0x0E) != 0:
            continue
        name = cstr(data, stroff + strx, stroff + strx + 256)
        if name not in names:
            continue
        desc = struct.unpack_from("<H", data, entry + 6)[0]
        struct.pack_into("<H", data, entry + 6, (desc & 0xFF) | (ordinal << 8))
        done.add(name)
    return done


def info(path: str) -> None:
    data = thin_arm64(path)
    h = header(data)
    print(f"{path} filetype={h['ftype']}")
    for off, cmd, size in commands(data):
        if cmd == LC_BUILD_VERSION:
            platform, minos, sdk = struct.unpack_from("<III", data, off + 8)
            print(
                f"  build_version platform={platform} minos={minos >> 16}.{(minos >> 8) & 255} "
                f"sdk={sdk >> 16}.{(sdk >> 8) & 255}"
            )
        elif cmd in DYLIB_CMDS or cmd == LC_ID_DYLIB or cmd == LC_RPATH:
            print(f"  {cmd:#x} {dylib_name(data, off, size)[1]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", nargs="?")
    ap.add_argument("dst", nargs="?")
    ap.add_argument("--info", metavar="FILE")
    ap.add_argument("--minos", default="16.0")
    ap.add_argument("--sdk", default="26.0")
    ap.add_argument(
        "--reroute", metavar="FILE", help="symbols (one per line) to bind to the shim"
    )
    args = ap.parse_args()

    if args.info:
        info(args.info)
        return 0
    if not (args.src and args.dst):
        ap.error("need SRC DST")

    data = thin_arm64(args.src)
    log = set_platform(data, args.minos, args.sdk)
    log += rewrite_paths(data)
    log += make_loadable(data)
    log += dedupe_dylibs(data)
    if args.reroute:
        names = {
            line.strip()
            for line in open(args.reroute, encoding="utf-8")
            if line.strip() and not line.startswith("#")
        }
        log += reroute(data, names)

    os.makedirs(os.path.dirname(os.path.abspath(args.dst)), exist_ok=True)
    with open(args.dst, "wb") as f:
        f.write(data)
    print(f"{os.path.basename(args.dst)}:")
    for line in log:
        note(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
