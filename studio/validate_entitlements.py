#!/usr/bin/env python3
"""Validate the capabilities that StudPad asks SideStore to preserve."""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path
from typing import Mapping

REQUIRED_ENTITLEMENTS = (
    "get-task-allow",
    "com.apple.developer.kernel.increased-memory-limit",
    "com.apple.developer.kernel.extended-virtual-addressing",
)


def missing_entitlements(values: Mapping[str, object]) -> list[str]:
    return [key for key in REQUIRED_ENTITLEMENTS if values.get(key) is not True]


def read_entitlements(path: str | Path) -> dict[str, object]:
    with Path(path).open("rb") as stream:
        values = plistlib.load(stream)
    if not isinstance(values, dict):
        raise ValueError("entitlements plist must contain a dictionary")
    missing = missing_entitlements(values)
    if missing:
        raise ValueError("missing or false entitlements: " + ", ".join(missing))
    return values


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_entitlements.py <entitlements.plist>", file=sys.stderr)
        return 2
    try:
        read_entitlements(argv[1])
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        print(f"validate_entitlements.py: {exc}", file=sys.stderr)
        return 1
    print("entitlements: get-task-allow, increased-memory-limit, and extended-virtual-addressing requested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

