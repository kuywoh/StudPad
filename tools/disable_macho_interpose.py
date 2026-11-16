#!/usr/bin/env python3
"""Disable macOS allocator interposition in the retargeted iOS mimalloc dylib."""

from __future__ import annotations

import argparse
import struct
import sys

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
HEADER_SIZE = 32
SEGMENT_COMMAND_SIZE = 72
SECTION_SIZE = 80
INTERPOSE_TUPLE_SIZE = 16


def _fixed_name(data: bytes, offset: int) -> str:
    return data[offset : offset + 16].split(b"\0", 1)[0].decode("ascii", "replace")


def interpose_sections(data: bytes) -> list[tuple[str, int, int]]:
    """Return (segment name, section size, size-field offset) for __interpose sections."""
    if len(data) < HEADER_SIZE or struct.unpack_from("<I", data, 0)[0] != MH_MAGIC_64:
        raise ValueError("expected a thin 64-bit little-endian Mach-O")
    ncmds, sizeofcmds = struct.unpack_from("<II", data, 16)
    end = HEADER_SIZE + sizeofcmds
    if end > len(data):
        raise ValueError("load commands extend beyond the Mach-O file")
    sections = []
    offset = HEADER_SIZE
    for _ in range(ncmds):
        if offset + 8 > end:
            raise ValueError("truncated load command")
        cmd, cmdsize = struct.unpack_from("<II", data, offset)
        if cmdsize < 8 or offset + cmdsize > end:
            raise ValueError("invalid load command size")
        if cmd == LC_SEGMENT_64:
            if cmdsize < SEGMENT_COMMAND_SIZE:
                raise ValueError("truncated LC_SEGMENT_64")
            segment = _fixed_name(data, offset + 8)
            nsects = struct.unpack_from("<I", data, offset + 64)[0]
            if nsects > (cmdsize - SEGMENT_COMMAND_SIZE) // SECTION_SIZE:
                raise ValueError("section table extends beyond LC_SEGMENT_64")
            for index in range(nsects):
                section = offset + SEGMENT_COMMAND_SIZE + index * SECTION_SIZE
                if _fixed_name(data, section) == "__interpose":
                    size_offset = section + 40
                    size = struct.unpack_from("<Q", data, size_offset)[0]
                    sections.append((segment, size, size_offset))
        offset += cmdsize
    if offset != end:
        raise ValueError("load command sizes do not match sizeofcmds")
    return sections


def active_interpose_tuple_count(data: bytes) -> int:
    """Return the number of active tuples, rejecting malformed section sizes."""
    count = 0
    for _segment, size, _size_offset in interpose_sections(data):
        if size % INTERPOSE_TUPLE_SIZE:
            raise ValueError(f"__interpose section size {size} is not tuple aligned")
        count += size // INTERPOSE_TUPLE_SIZE
    return count


def disable_interposing(data: bytes) -> tuple[bytes, int, int]:
    """Zero the metadata size for every interpose tuple section, preserving other image data."""
    patched = bytearray(data)
    sections = interpose_sections(data)
    tuple_count = 0
    changed = 0
    for _segment, size, size_offset in sections:
        if size % INTERPOSE_TUPLE_SIZE:
            raise ValueError(f"__interpose section size {size} is not tuple aligned")
        if size:
            tuple_count += size // INTERPOSE_TUPLE_SIZE
            struct.pack_into("<Q", patched, size_offset, 0)
            changed += 1
    return bytes(patched), changed, tuple_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if active interpose tuples remain")
    parser.add_argument("--check-active", action="store_true", help="fail if no active interpose tuples remain")
    parser.add_argument("binary")
    args = parser.parse_args()
    with open(args.binary, "rb") as source:
        original = source.read()
    sections = interpose_sections(original)
    if args.check_active:
        count = active_interpose_tuple_count(original)
        if not count:
            print("ERROR: no active __interpose tuples found", file=sys.stderr)
            return 1
        print(f"mimalloc interpose check passed ({count} active tuple(s))")
        return 0
    if args.check:
        active = [(segment, size) for segment, size, _ in sections if size]
        if active:
            print(f"ERROR: active __interpose sections remain: {active}", file=sys.stderr)
            return 1
        print(f"mimalloc interpose check passed ({len(sections)} section(s), no active tuples)")
        return 0
    patched, section_count, tuple_count = disable_interposing(original)
    if patched != original:
        with open(args.binary, "wb") as output:
            output.write(patched)
    print(f"disabled {tuple_count} mimalloc interpose tuple(s) across {section_count} section(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
