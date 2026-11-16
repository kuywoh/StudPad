"""Regression tests for macOS framework dependencies retargeted to the iOS shim."""

import struct
import unittest

from tools.ios_retarget import (
    LC_DYLD_INFO_ONLY,
    LC_ID_DYLIB,
    LC_SEGMENT_64,
    MH_DYLIB,
    MH_EXECUTE,
    MH_MAGIC_64,
    SHIM,
    commands,
    make_loadable,
    map_install_name,
)


class FrameworkRetargetTests(unittest.TestCase):
    def test_audio_unit_paths_route_through_shim(self):
        for path in (
            "/System/Library/Frameworks/AudioUnit.framework/Versions/A/AudioUnit",
            "/System/Library/Frameworks/AudioUnit.framework/AudioUnit",
        ):
            with self.subTest(path=path):
                self.assertEqual(map_install_name(path), SHIM)

    def test_audio_toolbox_keeps_its_ios_framework_path(self):
        path = "/System/Library/Frameworks/AudioToolbox.framework/Versions/A/AudioToolbox"
        self.assertEqual(
            map_install_name(path),
            "/System/Library/Frameworks/AudioToolbox.framework/AudioToolbox",
        )


class ExecutableRetargetTests(unittest.TestCase):
    @staticmethod
    def segment(name, vmaddr, vmsize, fileoff, filesize, maxprot, initprot):
        return struct.pack(
            "<II16sQQQQiiII",
            LC_SEGMENT_64,
            72,
            name.encode().ljust(16, b"\0"),
            vmaddr,
            vmsize,
            fileoff,
            filesize,
            maxprot,
            initprot,
            0,
            0,
        )

    @classmethod
    def executable(cls, rebase, bind):
        segment_commands = b"".join(
            (
                cls.segment("__PAGEZERO", 0, 0x100000000, 0, 0, 0, 0),
                cls.segment("__TEXT", 0x100000000, 0x4000, 0, 0x1000, 5, 5),
                cls.segment("__DATA", 0x100004000, 0x4000, 0x1000, 0x1000, 3, 3),
            )
        )
        command_size = len(segment_commands) + 48
        rebase_off = 32 + command_size
        bind_off = rebase_off + len(rebase)
        dyld_info = struct.pack(
            "<12I",
            LC_DYLD_INFO_ONLY,
            48,
            rebase_off,
            len(rebase),
            bind_off,
            len(bind),
            0,
            0,
            0,
            0,
            0,
            0,
        )
        header = struct.pack(
            "<8I", MH_MAGIC_64, 0x0100000C, 0, MH_EXECUTE, 4, command_size, 0x200000, 0
        )
        return bytearray(header + segment_commands + dyld_info + rebase + bind)

    def test_make_loadable_remaps_classic_rebase_and_bind_segment_indexes(self):
        rebase = bytes((0x22, 0x00, 0x51, 0x00))  # segment 2, offset 0; rebase once; done
        bind = bytes((0x72, 0x00, 0x40)) + b"_symbol\0" + bytes((0x90, 0x00))
        data = self.executable(rebase, bind)

        make_loadable(data)

        filetype = struct.unpack_from("<I", data, 12)[0]
        self.assertEqual(filetype, MH_DYLIB)
        info_off = next(off for off, cmd, _size in commands(data) if cmd == LC_DYLD_INFO_ONLY)
        fields = struct.unpack_from("<10I", data, info_off + 8)
        self.assertEqual(data[fields[0]], 0x21)
        self.assertEqual(data[fields[2]], 0x71)
        self.assertIn(LC_ID_DYLIB, [cmd for _off, cmd, _size in commands(data)])

    def test_make_loadable_rejects_rebase_or_bind_into_pagezero(self):
        cases = (
            (bytes((0x20, 0x00, 0x51, 0x00)), b"", "rebase"),
            (b"", bytes((0x70, 0x00, 0x90, 0x00)), "bind"),
        )
        for rebase, bind, name in cases:
            with self.subTest(stream=name), self.assertRaisesRegex(
                SystemExit, f"{name}: opcode targets removed __PAGEZERO segment 0"
            ):
                make_loadable(self.executable(rebase, bind))


if __name__ == "__main__":
    unittest.main()