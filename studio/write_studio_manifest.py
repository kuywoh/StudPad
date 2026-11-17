#!/usr/bin/env python3
"""Create the small, pinned download manifest for the on-device Studio asset fetch."""

from __future__ import annotations

import hashlib
import plistlib
import re
import sys
import stat
import zipfile
from pathlib import Path
from urllib.parse import urlparse


def read_fetch(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def safe_resource_path(path: str) -> bool:
    if not path or path.startswith("/") or "\\" in path or "\x00" in path:
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    fetch_path: str | Path,
    package_path: str | Path,
    minimum_package_bytes: int = 100 * 1024 * 1024,
) -> dict[str, object]:
    values = read_fetch(fetch_path)
    required = ("version", "upload", "url", "bytes", "sha256", "app")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError("fetch record is missing: " + ", ".join(missing))

    upload = values["upload"]
    if not re.fullmatch(r"version-[A-Fa-f0-9]{8,64}", upload):
        raise ValueError("invalid Roblox Studio version upload")
    expected_url = f"https://setup.rbxcdn.com/mac/arm64/{upload}-RobloxStudioApp.zip"
    parsed = urlparse(values["url"])
    if parsed.scheme != "https" or parsed.netloc != "setup.rbxcdn.com" or values["url"] != expected_url:
        raise ValueError("download URL is not the version-pinned Roblox arm64 Studio package")
    app_name = Path(values["app"]).name
    if not app_name.endswith(".app") or "/" in app_name or "\\" in app_name:
        raise ValueError("invalid Studio app bundle name")
    if not re.fullmatch(r"[A-Za-z0-9 ._()-]{1,128}", values["version"]):
        raise ValueError("invalid Studio version string")

    package = Path(package_path)
    package_bytes = int(values["bytes"])
    if package_bytes <= minimum_package_bytes or package_bytes != package.stat().st_size:
        raise ValueError("downloaded package size does not match fetch record")
    package_sha = values["sha256"].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", package_sha) or sha256_file(package) != package_sha:
        raise ValueError("downloaded package checksum does not match fetch record")

    prefix = f"{app_name}/Contents/Resources/"
    resource_files = 0
    resource_bytes = 0
    seen: set[str] = set()
    with zipfile.ZipFile(package) as archive:
        infos = archive.infolist()
        if not infos or len(infos) >= 65535:
            raise ValueError("unsupported Studio ZIP entry count")
        for info in infos:
            if info.file_size >= 0xFFFFFFFF or info.compress_size >= 0xFFFFFFFF or info.header_offset >= 0xFFFFFFFF:
                raise ValueError("ZIP64 Studio packages are not supported")
            if not info.filename.startswith(prefix):
                continue
            relative = info.filename[len(prefix):]
            is_dir = info.is_dir() or info.external_attr >> 16 & 0o170000 == 0o040000
            if is_dir and relative.endswith("/"):
                relative = relative[:-1]
            if not relative:
                continue
            if not safe_resource_path(relative):
                raise ValueError("unsafe Studio resource path")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise ValueError("symlink in Studio resource archive")
            if is_dir:
                continue
            if mode not in (0, stat.S_IFREG):
                raise ValueError("special file in Studio resource archive")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError("unsupported Studio resource compression")
            if info.filename in seen:
                raise ValueError("duplicate Studio resource path")
            seen.add(info.filename)
            resource_files += 1
            resource_bytes += info.file_size

    if resource_files == 0:
        raise ValueError("Studio package contains no Resources files")
    return {
        "studio_version": values["version"],
        "package_url": values["url"],
        "package_bytes": package_bytes,
        "package_sha256": package_sha,
        "app_bundle_name": app_name,
        "resource_files": resource_files,
        "resource_bytes": resource_bytes,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: write_studio_manifest.py <fetch.txt> <studio.zip> <output.plist>", file=sys.stderr)
        return 2
    try:
        manifest = build_manifest(argv[1], argv[2])
        with Path(argv[3]).open("wb") as stream:
            plistlib.dump(manifest, stream, fmt=plistlib.FMT_XML, sort_keys=True)
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as exc:
        print(f"write_studio_manifest.py: {exc}", file=sys.stderr)
        return 1
    print(
        f"Studio content manifest: {manifest['studio_version']}; "
        f"{manifest['resource_files']} files, {manifest['resource_bytes']} resource bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
