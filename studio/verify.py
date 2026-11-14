#!/usr/bin/env python3
"""Fail the build unless the probe IPA has the Mach-O shape the host expects."""
import plistlib
import struct
import sys
import zipfile

MH_MAGIC_64 = 0xFEEDFACF
MH_EXECUTE = 2
MH_BUNDLE = 8
LC_LOAD_DYLIB = 0xC
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_MAIN = 0x80000028
LC_BUILD_VERSION = 0x32
LC_CODE_SIGNATURE = 0x1D

GUEST = "Payload/StudPadStudioProbe.app/Frameworks/StudioKit.framework/StudioKit"
HOST = "Payload/StudPadStudioProbe.app/StudPadStudioProbe"
QTCORE = "Payload/StudPadStudioProbe.app/Frameworks/QtCore.framework/Versions/5/QtCore"


def fail(msg):
    raise SystemExit("verify.py: " + msg)


def commands(data):
    magic, _cpu, _sub, filetype, ncmds, sizeofcmds, _flags, _ = struct.unpack_from(
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


def bind_stats(data, off, size):
    i, end = off, off + size
    total = weak = 0
    while i < end:
        raw = data[i]
        op = raw & 0xF0
        i += 1
        if op == 0:
            continue
        if op in (0x10, 0x30, 0x50, 0x90, 0xB0):
            continue
        if op in (0x20, 0x70, 0x80, 0xA0, 0x60):
            while i < end:
                b = data[i]
                i += 1
                if not b & 0x80:
                    break
            continue
        if op == 0x40:
            total += 1
            if raw & 1:
                weak += 1
            i = data.index(b"\0", i, end) + 1
            continue
        if op == 0xC0:
            for _ in range(2):
                while i < end:
                    b = data[i]
                    i += 1
                    if not b & 0x80:
                        break
            continue
        fail(f"unexpected bind opcode {raw:#x}")
    return total, weak


def main():
    if len(sys.argv) != 2:
        fail("usage: verify.py <ipa>")
    z = zipfile.ZipFile(sys.argv[1])
    names = set(z.namelist())
    for required in (
        HOST,
        "Payload/StudPadStudioProbe.app/Info.plist",
        GUEST,
        "Payload/StudPadStudioProbe.app/Frameworks/StudioKit.framework/Info.plist",
        "Payload/StudPadStudioProbe.app/Frameworks/PlugIns/platforms/libqoffscreen.dylib",
        "Payload/StudPadStudioProbe.app/libfbxsdk.dylib",
        "Payload/StudPadStudioProbe.app/qt.conf",
    ):
        if required not in names:
            fail(f"missing {required}")

    data = z.read(GUEST)
    filetype, cmds = commands(data)
    if filetype != MH_BUNDLE:
        fail(f"guest filetype is {filetype}, expected MH_BUNDLE")
    platform = None
    has_main = False
    has_sig = False
    weak_libs = []
    mapped = []
    total = weak = 0
    for cmd, size, off in cmds:
        if cmd == LC_BUILD_VERSION:
            platform = struct.unpack_from("<I", data, off + 8)[0]
        elif cmd == LC_MAIN:
            has_main = True
        elif cmd == LC_CODE_SIGNATURE:
            has_sig = True
        elif cmd in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB):
            path = dylib_path(data, off, size)
            if cmd == LC_LOAD_WEAK_DYLIB:
                weak_libs.append(path)
            if "Foundation.framework" in path or "WebKit.framework" in path:
                mapped.append(path)
        elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
            fields = struct.unpack_from("<10I", data, off + 8)
            for bo, bs in ((fields[2], fields[3]), (fields[6], fields[7])):
                t, w = bind_stats(data, bo, bs)
                total += t
                weak += w
    if platform != 2:
        fail(f"guest platform is {platform}, expected iOS (2)")
    if not has_main:
        fail("guest has no LC_MAIN")
    if not total or weak != total:
        fail(f"guest weak bindings {weak}/{total}, expected all")
    if not any("AppKit.framework" in p for p in weak_libs):
        fail("guest does not mark AppKit weak")
    if not any("Foundation.framework" in p for p in mapped):
        fail("guest does not map Foundation to the iOS path")

    host_data = z.read(HOST)
    host_type, host_cmds = commands(host_data)
    host_platform = next(
        (struct.unpack_from("<I", host_data, off + 8)[0] for cmd, _s, off in host_cmds if cmd == LC_BUILD_VERSION),
        None,
    )
    if host_type != MH_EXECUTE or host_platform != 2:
        fail(f"host filetype/platform {host_type}/{host_platform}, expected 2/2")

    qt_data = z.read(QTCORE)
    qt_type, qt_cmds = commands(qt_data)
    qt_platform = next(
        (struct.unpack_from("<I", qt_data, off + 8)[0] for cmd, _s, off in qt_cmds if cmd == LC_BUILD_VERSION),
        None,
    )
    if qt_type != 6 or qt_platform != 2:
        fail(f"QtCore filetype/platform {qt_type}/{qt_platform}, expected 6/2")

    plist = plistlib.loads(z.read("Payload/StudPadStudioProbe.app/Info.plist"))
    if plist.get("UIFileSharingEnabled") is not True:
        fail("Documents sharing is off")
    host_name = plist.get("CFBundleExecutable")
    if host_name != "StudPadStudioProbe":
        fail(f"CFBundleExecutable is {host_name!r}, expected StudPadStudioProbe")
    info = z.getinfo(HOST)
    mode = (info.external_attr >> 16) & 0o777
    if not mode & 0o111:
        fail(f"host executable mode is {mode:o}, expected an executable bit")

    print(
        f"verify: guest MH_BUNDLE iOS, LC_MAIN, weak binds {weak}/{total}, "
        f"signature blob present={has_sig}; host MH_EXECUTE iOS mode={mode:o}; "
        f"CFBundleExecutable={host_name}; QtCore dylib iOS; "
        f"IPA {sum(i.file_size for i in z.infolist())} bytes uncompressed"
    )


if __name__ == "__main__":
    main()
