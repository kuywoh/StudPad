"""Regression tests for macOS framework dependencies retargeted to the iOS shim."""

import struct
import unittest

from tools.ios_retarget import (
    LC_DYLD_CHAINED_FIXUPS,
    LC_DYLD_INFO_ONLY,
    LC_ID_DYLIB,
    LC_LOAD_DYLINKER,
    LC_SEGMENT_64,
    MH_DYLIB,
    MH_EXECUTE,
    MH_MAGIC_64,
    MH_NO_REEXPORTED_DYLIBS,
    MH_PIE,
    SHIM,
    commands,
    dylib_name,
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
    def segment(name, vmaddr, vmsize, fileoff, filesize, maxprot, initprot, text_offset=None):
        section = b""
        if text_offset is not None:
            section = struct.pack(
                "<16s16sQQIIIIIIII",
                b"__text\0".ljust(16, b"\0"),
                b"__TEXT\0".ljust(16, b"\0"),
                0x100001000,
                0x1000,
                text_offset,
                2,
                0,
                0,
                0,
                0,
                0,
                0,
            )
        return struct.pack(
            "<II16sQQQQiiII",
            LC_SEGMENT_64,
            72 + len(section),
            name.encode().ljust(16, b"\0"),
            vmaddr,
            vmsize,
            fileoff,
            filesize,
            maxprot,
            initprot,
            int(bool(section)),
            0,
        ) + section

    @classmethod
    def executable(cls, rebase, bind, chained=False, linker=False, no_slack=False):
        def segments(text_offset):
            return b"".join(
                (
                    cls.segment("__PAGEZERO", 0, 0x100000000, 0, 0, 0, 0),
                    cls.segment(
                        "__TEXT", 0x100000000, 0x4000, 0, 0x2000, 5, 5, text_offset
                    ),
                    cls.segment("__DATA", 0x100004000, 0x4000, 0x2000, 0x1000, 3, 3),
                )
            )

        segment_commands = segments(0x1000)
        command_size = len(segment_commands) + 48 + (16 if chained else 0) + (32 if linker else 0)
        if no_slack:
            segment_commands = segments(32 + command_size)
            command_size = len(segment_commands) + 48 + (16 if chained else 0) + (32 if linker else 0)
        rebase_off = 0x3000
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
        chained_data = b"\0\0\0\0" if chained else b""
        linker_name = b"/usr/lib/dyld\0"
        linker_command = (
            struct.pack("<III", LC_LOAD_DYLINKER, 32, 12)
            + linker_name
            + b"\0" * (32 - 12 - len(linker_name))
            if linker
            else b""
        )
        chained_command = (
            struct.pack(
                "<IIII", LC_DYLD_CHAINED_FIXUPS, 16, bind_off + len(bind), len(chained_data)
            )
            if chained
            else b""
        )
        header = struct.pack(
            "<8I",
            MH_MAGIC_64,
            0x0100000C,
            0,
            MH_EXECUTE,
            4 + int(chained) + int(linker),
            command_size,
            MH_PIE,
            0,
        )
        commands = header + segment_commands + dyld_info + linker_command + chained_command
        return bytearray(
            commands
            + b"\0" * (rebase_off - len(commands))
            + rebase
            + bind
            + chained_data
        )

    def test_make_loadable_preserves_pagezero_and_dyld_segment_indexes(self):
        rebase = bytes((0x22, 0x00, 0x51, 0x00))  # segment 2, offset 0; rebase once; done
        bind = bytes((0x72, 0x00, 0x40)) + b"_symbol\0" + bytes((0x90, 0x00))
        data = self.executable(rebase, bind)

        make_loadable(data)

        filetype = struct.unpack_from("<I", data, 12)[0]
        self.assertEqual(filetype, MH_DYLIB)
        flags = struct.unpack_from("<I", data, 24)[0]
        self.assertFalse(flags & MH_PIE)
        self.assertTrue(flags & MH_NO_REEXPORTED_DYLIBS)
        segment_commands = [
            (off, size)
            for off, cmd, size in commands(data)
            if cmd == LC_SEGMENT_64
        ]
        self.assertEqual(len(segment_commands), 3)
        pagezero, _size = segment_commands[0]
        self.assertEqual(struct.unpack_from("<QQ", data, pagezero + 24), (0xFFFFC000, 0x4000))
        info_off = next(off for off, cmd, _size in commands(data) if cmd == LC_DYLD_INFO_ONLY)
        fields = struct.unpack_from("<10I", data, info_off + 8)
        self.assertEqual(data[fields[0] : fields[0] + fields[1]], rebase)
        self.assertEqual(data[fields[2] : fields[2] + fields[3]], bind)
        id_off, id_size = next(
            (off, size) for off, cmd, size in commands(data) if cmd == LC_ID_DYLIB
        )
        self.assertEqual(dylib_name(data, id_off, id_size)[1], "@rpath/StudioKit.dylib")

    def test_make_loadable_reuses_dylinker_command_when_padding_is_too_small(self):
        data = self.executable(b"\0", b"\0", linker=True, no_slack=True)

        make_loadable(data)

        self.assertNotIn(LC_LOAD_DYLINKER, [cmd for _off, cmd, _size in commands(data)])
        id_off, id_size = next(
            (off, size) for off, cmd, size in commands(data) if cmd == LC_ID_DYLIB
        )
        self.assertEqual(dylib_name(data, id_off, id_size)[1], "StudPad")

    def test_make_loadable_keeps_chained_fixup_segment_table_valid(self):
        data = self.executable(b"\0", b"\0", chained=True)
        original = bytes(data)

        make_loadable(data)

        self.assertEqual(
            [cmd for _off, cmd, _size in commands(data)].count(LC_DYLD_CHAINED_FIXUPS), 1
        )
        chain = next(
            off for off, cmd, _size in commands(data) if cmd == LC_DYLD_CHAINED_FIXUPS
        )
        self.assertEqual(data[chain : chain + 16], original[chain : chain + 16])


if __name__ == "__main__":
    unittest.main()
