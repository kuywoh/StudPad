#!/usr/bin/env python3
"""Refuse the build unless the IPA has the shape the host and dyld expect.

Structural only: it proves the packaging, the retargeting and the linking happened, not that Studio
runs. What Studio does is in Documents/studio.log on the iPad.
"""

import os
import plistlib
import re
import struct
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.disable_macho_interpose import active_interpose_tuple_count

MH_MAGIC_64 = 0xFEEDFACF
MH_EXECUTE = 2
MH_DYLIB = 6
LC_LOAD_DYLIB = 0xC
LC_ID_DYLIB = 0xD
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_LOAD_UPWARD_DYLIB = 0x80000023
LC_REEXPORT_DYLIB = 0x8000001F
LC_MAIN = 0x80000028
LC_BUILD_VERSION = 0x32

DYLIB_CMDS = {LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LOAD_UPWARD_DYLIB}
LOAD_DYLIB_CMDS = {LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LOAD_UPWARD_DYLIB}

ROOT = "Payload/StudPadStudio.app"
GUEST = f"{ROOT}/Frameworks/StudioKit"
HOST = f"{ROOT}/StudPadStudio"
SHIM = f"{ROOT}/Frameworks/libMacShim.dylib"
MIMALLOC = f"{ROOT}/Frameworks/libmimalloc.3.dylib"
QTCORE = f"{ROOT}/Frameworks/libQtCore.dylib"
QCOCOA = f"{ROOT}/Frameworks/PlugIns/platforms/libqcocoa.dylib"
MANIFEST = f"{ROOT}/StudioPackage.plist"


def fail(msg):
    raise SystemExit("verify.py: " + msg)


def commands(data):
    magic, _cpu, _sub, filetype, ncmds, _sizeofcmds, _flags, _ = struct.unpack_from(
        "<IiiIIIII", data, 0
    )
    if magic != MH_MAGIC_64:
        fail(f"bad Mach-O magic {magic:#x}")
    out = []
    off = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        out.append((cmd, cmdsize, off))
        off += cmdsize
    return filetype, out


def dylib_path(data, off, cmdsize):
    name_off = struct.unpack_from("<I", data, off + 8)[0]
    start = off + name_off
    end = data.index(b"\0", start, off + cmdsize)
    return data[start:end].decode()


def inspect(data):
    filetype, cmds = commands(data)
    platform = None
    has_main = False
    install_id = None
    loads = []
    for cmd, size, off in cmds:
        if cmd == LC_BUILD_VERSION:
            platform = struct.unpack_from("<I", data, off + 8)[0]
        elif cmd == LC_MAIN:
            has_main = True
        elif cmd == LC_ID_DYLIB:
            install_id = dylib_path(data, off, size)
        elif cmd in LOAD_DYLIB_CMDS:
            loads.append(dylib_path(data, off, size))
    return dict(filetype=filetype, platform=platform, has_main=has_main, id=install_id, loads=loads)


def validate_device_family(plist):
    """Refuse an IPA iPadOS would run as an iPhone app.

    Without 2 (iPad) in UIDeviceFamily the app installs as iPhone-only, and iPadOS presents it in
    compatibility mode with a 320x480 canvas. Build 97 logged exactly that screen size from Qt, so
    Studio had a letterboxed display instead of the iPad's.
    """
    family = plist.get("UIDeviceFamily")
    if not isinstance(family, list) or 2 not in family:
        fail(
            f"UIDeviceFamily is {family!r}: 2 (iPad) is required, or iPadOS runs the app "
            "letterboxed in a 320x480 iPhone canvas"
        )


def validate_bundle_version(plist, expected=None):
    version = plist.get("CFBundleVersion")
    if not isinstance(version, str) or not version.strip():
        fail("no CFBundleVersion: the installed app cannot identify its build")
    if expected and version != expected:
        fail(f"CFBundleVersion is {version!r}, expected workflow run {expected!r}")


def main():
    if len(sys.argv) != 2:
        fail("usage: verify.py <ipa>")
    ipa = sys.argv[1]
    z = zipfile.ZipFile(ipa)
    names = set(z.namelist())

    for required in (HOST, f"{ROOT}/Info.plist", GUEST, SHIM, MIMALLOC, QTCORE, QCOCOA, MANIFEST, f"{ROOT}/qt.conf"):
        if required not in names:
            fail(f"missing {required}")

    guest = inspect(z.read(GUEST))
    if guest["filetype"] != MH_DYLIB:
        fail(f"guest filetype {guest['filetype']}, expected MH_DYLIB ({MH_DYLIB})")
    if guest["platform"] != 2:
        fail(f"guest platform {guest['platform']}, expected iOS (2)")
    if not guest["has_main"]:
        fail("guest has no LC_MAIN: the host cannot find Studio's entry point")
    # The host opens StudioKit by bundle path, so this short ID is safe if load-command padding is unavailable.
    if guest["id"] not in ("@rpath/StudioKit.dylib", "StudPad"):
        fail(f"guest LC_ID_DYLIB is {guest['id']!r}")
    if "@rpath/libMacShim.dylib" not in guest["loads"]:
        fail("guest does not link libMacShim.dylib: AppKit was not redirected")
    for path in guest["loads"]:
        if ".framework/Versions/" in path:
            fail(f"guest still uses a macOS framework layout: {path}")
        if path.startswith("/System/Library/Frameworks/") and ".framework/Versions" not in path:
            name = path.split("/")[4].split(".")[0]
            if name in ("AppKit", "Cocoa", "Carbon", "ApplicationServices"):
                fail(f"guest still imports {path}: it would not load on iOS")

    qt = inspect(z.read(QTCORE))
    if qt["filetype"] != MH_DYLIB or qt["platform"] != 2:
        fail(f"QtCore filetype/platform {qt['filetype']}/{qt['platform']}, expected 6/2")
    if qt["id"] != "@rpath/libQtCore.dylib":
        fail(f"QtCore LC_ID_DYLIB is {qt['id']!r}, expected the flat name")

    interpose_count = active_interpose_tuple_count(z.read(MIMALLOC))
    if not interpose_count:
        fail("mimalloc allocator interposition is missing or disabled")
    # Active tuples are not enough: dyld only reads them from an image loaded at launch, so the
    # guest must keep binding mi_* to the dylib and the host must load it (build.sh links it).
    if not any("libmimalloc" in p for p in guest["loads"]):
        fail("guest does not link Studio's mimalloc: its mi_* imports would not resolve")

    shim = inspect(z.read(SHIM))
    if shim["filetype"] != MH_DYLIB or shim["platform"] != 2:
        fail(f"shim filetype/platform {shim['filetype']}/{shim['platform']}, expected 6/2")
    if shim["id"] != "@rpath/libMacShim.dylib":
        fail(f"shim LC_ID_DYLIB is {shim['id']!r}")
    # Studio takes `~` from the passwd entry (StudioKit imports getpwuid/getpwuid_r, Qt getpwnam_r),
    # and iOS reports /var/mobile there; the sandbox then refuses Studio's ~/Library/Roblox mkdir.
    # The shim interposes those calls to report the app container, so the tuples must be in the
    # shipped dylib: dyld only reads __interpose from launch images, and the host links the shim.
    # exit() is interposed as well: it is the only marker that says Studio quit instead of crashing.
    # _NSGetExecutablePath answers with the guest path so Studio's install lookup lands in the
    # RobloxStudio.app it was given instead of in App.app/../Resources.
    shim_interposers = active_interpose_tuple_count(z.read(SHIM))
    if shim_interposers < 6:
        fail(
            f"shim has {shim_interposers} active __interpose tuple(s); the passwd home "
            "redirection needs getpwuid, getpwuid_r, getpwnam and getpwnam_r, the exit marker "
            "needs exit, and Studio's installation lookup needs _NSGetExecutablePath"
        )

    host_data = z.read(HOST)
    host = inspect(host_data)
    if host["filetype"] != MH_EXECUTE or host["platform"] != 2:
        fail(f"host filetype/platform {host['filetype']}/{host['platform']}, expected 2/2")
    if "@rpath/libMacShim.dylib" not in host["loads"]:
        fail("host does not link the shim, so studpad_guest_start cannot be called")
    if not any("libmimalloc" in p for p in host["loads"]):
        fail(
            "host does not load Studio's mimalloc at launch: dyld only applies its malloc "
            "interposition to launch images, so Qt and StudioKit would use different heaps"
        )
    mode = (z.getinfo(HOST).external_attr >> 16) & 0o777
    if not mode & 0o111:
        fail(f"host executable mode is {mode:o}")

    plist = plistlib.loads(z.read(f"{ROOT}/Info.plist"))
    if plist.get("CFBundleExecutable") != "StudPadStudio":
        fail(f"CFBundleExecutable is {plist.get('CFBundleExecutable')!r}")
    if plist.get("CFBundleIdentifier") != "com.kuywoh.studpadstudio":
        fail(f"unexpected CFBundleIdentifier: {plist.get('CFBundleIdentifier')!r}")
    validate_bundle_version(plist, os.environ.get("GITHUB_RUN_NUMBER"))
    validate_device_family(plist)
    if plist.get("UIFileSharingEnabled") is not True:
        fail("Documents sharing is off: the log would not be readable")
    if "UIApplicationSceneManifest" not in plist:
        fail("no scene manifest: iPadOS 26 leaves the app on a black screen")

    manifest = plistlib.loads(z.read(MANIFEST))
    required_manifest_keys = {
        "studio_version", "package_url", "package_bytes", "package_sha256",
        "app_bundle_name", "resource_files", "resource_bytes",
    }
    if not required_manifest_keys.issubset(manifest):
        fail("StudioPackage.plist is missing download metadata")
    if not manifest["package_url"].startswith("https://setup.rbxcdn.com/mac/arm64/version-") or not manifest["package_url"].endswith("-RobloxStudioApp.zip"):
        fail("StudioPackage.plist is not pinned to the Roblox Mac Studio CDN")
    if not isinstance(manifest["package_bytes"], int) or manifest["package_bytes"] <= 100 * 1024 * 1024:
        fail("StudioPackage.plist has an invalid package size")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest["package_sha256"]):
        fail("StudioPackage.plist has an invalid SHA-256")
    if not manifest["app_bundle_name"].endswith(".app") or manifest["resource_files"] <= 0:
        fail("StudioPackage.plist has invalid app or resource metadata")
    if any(name.startswith(f"{ROOT}/Resources/") for name in names):
        fail("large Studio Resources are still embedded in the installer IPA")

    print(
        f"verify: bundle ID {plist['CFBundleIdentifier']}; guest MH_DYLIB iOS + LC_MAIN + shim link; "
        f"QtCore flat dylib; mimalloc interposition active ({interpose_count} tuples) and a host "
        f"launch load command; shim {len(shim['loads'])} re-exported frameworks and "
        f"{shim_interposers} interposer(s); "
        f"host MH_EXECUTE iOS mode={mode:o}; Studio resources download pinned to "
        f"{manifest['studio_version']}; IPA {sum(i.file_size for i in z.infolist())} bytes uncompressed"
    )


if __name__ == "__main__":
    main()
