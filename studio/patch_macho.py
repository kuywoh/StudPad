#!/usr/bin/env python3
"""Prepare Studio's macOS arm64 Mach-Os for an iOS dyld probe.

What it changes, in place:

  --main            MH_EXECUTE -> MH_BUNDLE (dyld refuses to dlopen an executable)
  every load cmd    macOS framework path -> iOS unversioned path where one exists
  absent libraries  AppKit, ApplicationServices, Carbon, ForceFeedback, DiskArbitration,
                    OpenGL, ColorSync, Cocoa, libcups are marked LC_LOAD_WEAK_DYLIB
  dyld-info binds   every imported symbol is marked weak (BIND_SYMBOL_FLAGS_WEAK_IMPORT),
                    so a symbol iOS does not provide binds to NULL instead of failing the load

The original macOS code signature is left in place; SideStore re-signs the whole app. Platform
LC_BUILD_VERSION is set to iOS separately with vtool in build.sh.

This is deliberately a load probe, not an AppKit implementation. A NULL import that is actually
called will fault, and the host logs the backtrace.
"""
from __future__ import annotations

import argparse
import re
import struct
import sys

MH_MAGIC_64 = 0xFEEDFACF
MH_EXECUTE = 2
MH_BUNDLE = 8
LC_LOAD_DYLIB = 0xC
LC_ID_DYLIB = 0xD
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_REEXPORT_DYLIB = 0x8000001F
LC_LOAD_UPWARD_DYLIB = 0x80000023
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022

DYLIB_COMMANDS = {LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LOAD_UPWARD_DYLIB}

# The build installs Qt as plain dylibs, not framework bundles, so SideStore's nested-framework
# executable check never sees them. Every Qt framework reference must become @rpath/libQtX.dylib.
QT_FRAMEWORK = re.compile(r"^@rpath/(Qt[A-Za-z0-9]+)\.framework(?:/.*)?$")


def flatten_qt(path: str) -> str:
    m = QT_FRAMEWORK.match(path)
    return f"@rpath/lib{m.group(1)}.dylib" if m else path

# macOS frameworks with no iOS equivalent. Their load commands become weak, and their symbols
# are weak imports, so dyld can finish the load and a call can be diagnosed at runtime.
ABSENT = {
    "AppKit",
    "Cocoa",
    "ApplicationServices",
    "Carbon",
    "ForceFeedback",
    "DiskArbitration",
    "OpenGL",
    "ColorSync",
}

FRAMEWORK_PREFIX = "/System/Library/Frameworks/"


def framework_name(path: str) -> str | None:
    if not path.startswith(FRAMEWORK_PREFIX):
        return None
    head = path[len(FRAMEWORK_PREFIX):].split("/", 1)[0]
    if not head.endswith(".framework"):
        return None
    return head[: -len(".framework")]


def ios_path(path: str) -> str | None:
    """The iOS path for a macOS dependency, or None if it is absent and should be weak."""
    name = framework_name(path)
    if name:
        if name in ABSENT:
            return None
        return f"{FRAMEWORK_PREFIX}{name}.framework/{name}"
    if path.startswith("/usr/lib/libcups"):
        return None
    return path


def load_commands(data: bytearray):
    magic, _cputype, _sub, _filetype, ncmds, sizeofcmds, _flags, _ = struct.unpack_from(
        "<IiiIIIII", data, 0
    )
    if magic != MH_MAGIC_64:
        raise ValueError(f"not a thin 64-bit little-endian Mach-O (magic {magic:#x})")
    off = 32
    end = off + sizeofcmds
    for _ in range(ncmds):
        if off + 8 > end:
            raise ValueError("load commands truncated")
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmdsize < 8 or off + cmdsize > end:
            raise ValueError(f"bad load command at {off}")
        yield off, cmd, cmdsize
        off += cmdsize


def skip_uleb(data: bytearray, i: int, end: int) -> int:
    while i < end:
        b = data[i]
        i += 1
        if not b & 0x80:
            return i
    raise ValueError("truncated ULEB")


def skip_sleb(data: bytearray, i: int, end: int) -> int:
    return skip_uleb(data, i, end)


def weaken_bind_stream(data: bytearray, start: int, size: int) -> int:
    """Set the weak-import flag on every SET_SYMBOL_TRAILING_FLAGS_IMM opcode."""
    if not size:
        return 0
    i, end = start, start + size
    changed = 0
    while i < end:
        raw = data[i]
        op, _imm = raw & 0xF0, raw & 0x0F
        i += 1
        if op == 0x00:  # DONE
            continue
        if op in (0x10, 0x30, 0x50, 0x90, 0xB0):  # immediate-only opcodes
            continue
        if op in (0x20, 0x70, 0x80, 0xA0):  # one ULEB
            i = skip_uleb(data, i, end)
            continue
        if op == 0x40:  # SET_SYMBOL_TRAILING_FLAGS_IMM
            if not raw & 0x1:
                data[i - 1] = raw | 0x1
                changed += 1
            nul = data.find(b"\0", i, end)
            if nul < 0:
                raise ValueError("unterminated bind symbol")
            i = nul + 1
            continue
        if op == 0x60:  # SET_ADDEND_SLEB
            i = skip_sleb(data, i, end)
            continue
        if op == 0xC0:  # DO_BIND_ULEB_TIMES_SKIPPING_ULEB
            i = skip_uleb(data, i, end)
            i = skip_uleb(data, i, end)
            continue
        raise ValueError(f"unsupported bind opcode {raw:#x}")
    return changed


def patch(path: str, is_main: bool) -> None:
    with open(path, "rb") as f:
        data = bytearray(f.read())

    if is_main:
        filetype = struct.unpack_from("<I", data, 12)[0]
        if filetype != MH_EXECUTE:
            raise ValueError(f"{path}: expected MH_EXECUTE, found {filetype}")
        struct.pack_into("<I", data, 12, MH_BUNDLE)

    changed_paths = 0
    weak_cmds = 0
    weak_binds = 0

    for off, cmd, cmdsize in list(load_commands(data)):
        if cmd == LC_ID_DYLIB:
            name_off = struct.unpack_from("<I", data, off + 8)[0]
            start = off + name_off
            nul = data.find(b"\0", start, off + cmdsize)
            if nul < 0:
                raise ValueError(f"{path}: unterminated dylib id")
            old = bytes(data[start:nul]).decode("utf-8", "replace")
            new = flatten_qt(old)
            if new != old:
                encoded = new.encode()
                capacity = cmdsize - name_off
                if len(encoded) + 1 > capacity:
                    raise ValueError(f"{path}: flattened id {new!r} does not fit")
                data[start:start + capacity] = encoded + b"\0" * (capacity - len(encoded))
                changed_paths += 1
            continue
        if cmd in DYLIB_COMMANDS:
            name_off = struct.unpack_from("<I", data, off + 8)[0]
            if name_off >= cmdsize:
                raise ValueError(f"{path}: dylib name offset past command")
            start = off + name_off
            nul = data.find(b"\0", start, off + cmdsize)
            if nul < 0:
                raise ValueError(f"{path}: unterminated dylib path")
            old = bytes(data[start:nul]).decode("utf-8", "replace")
            new = flatten_qt(old)
            if new == old:
                new = ios_path(old)
            if new is None or framework_name(old) in ABSENT:
                if cmd != LC_LOAD_WEAK_DYLIB:
                    struct.pack_into("<I", data, off, LC_LOAD_WEAK_DYLIB)
                    weak_cmds += 1
            elif new != old:
                encoded = new.encode()
                capacity = cmdsize - name_off
                if len(encoded) + 1 > capacity:
                    raise ValueError(
                        f"{path}: new path {new!r} does not fit {old!r} ({capacity} bytes)"
                    )
                data[start:start + capacity] = encoded + b"\0" * (capacity - len(encoded))
                changed_paths += 1
        elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
            if cmdsize < 48:
                raise ValueError(f"{path}: short dyld_info command")
            fields = struct.unpack_from("<10I", data, off + 8)
            binding_off, binding_size = fields[2], fields[3]
            lazy_off, lazy_size = fields[6], fields[7]
            weak_binds += weaken_bind_stream(data, binding_off, binding_size)
            weak_binds += weaken_bind_stream(data, lazy_off, lazy_size)
        elif cmd == 0x80000028:  # LC_MAIN in the guest; left for the host to call
            pass

    with open(path, "wb") as f:
        f.write(data)
    print(
        f"patched {path}: filetype={'MH_BUNDLE' if is_main else 'dylib'} "
        f"paths={changed_paths} weak_libs={weak_cmds} weak_binds={weak_binds}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", action="store_true", help="retype MH_EXECUTE to MH_BUNDLE")
    ap.add_argument("path")
    args = ap.parse_args()
    try:
        patch(args.path, args.main)
    except Exception as e:  # noqa: BLE001 - build script should show the exact file and reason
        print(f"patch_macho.py: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
