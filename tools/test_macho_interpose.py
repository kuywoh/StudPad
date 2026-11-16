"""Tests that macOS interpose tuples are removed without changing other Mach-O data."""

import struct
import unittest

from tools.disable_macho_interpose import (
    active_interpose_tuple_count,
    disable_interposing,
    interpose_sections,
)


MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19


def mach_o_with_interpose(size=32):
    command_size = 72 + 80
    data = bytearray(32 + command_size)
    struct.pack_into("<IiiIIIII", data, 0, MH_MAGIC_64, 0x0100000C, 0, 6, 1, command_size, 0, 0)
    struct.pack_into("<II", data, 32, LC_SEGMENT_64, command_size)
    data[40:56] = b"__DATA_CONST".ljust(16, b"\0")
    struct.pack_into("<I", data, 32 + 64, 1)
    section = 32 + 72
    data[section : section + 16] = b"__interpose".ljust(16, b"\0")
    data[section + 16 : section + 32] = b"__DATA_CONST".ljust(16, b"\0")
    struct.pack_into("<QQ", data, section + 32, 0x1000, size)
    return bytes(data)


class InterposeSectionTests(unittest.TestCase):
    def test_counts_active_allocator_interpose_tuples(self):
        self.assertEqual(active_interpose_tuple_count(mach_o_with_interpose()), 2)

    def test_disabled_interpose_section_has_no_active_tuples(self):
        patched, _, _ = disable_interposing(mach_o_with_interpose())
        self.assertEqual(active_interpose_tuple_count(patched), 0)

    def test_disables_interpose_tuples_and_preserves_other_bytes(self):
        original = mach_o_with_interpose()
        patched, sections, tuples = disable_interposing(original)
        self.assertEqual((sections, tuples), (1, 2))
        self.assertEqual(interpose_sections(patched)[0][1], 0)
        self.assertEqual(patched[:144], original[:144])
        self.assertEqual(patched[152:], original[152:])

    def test_image_without_interpose_section_is_unchanged(self):
        data = bytearray(32 + 72)
        struct.pack_into("<IiiIIIII", data, 0, MH_MAGIC_64, 0x0100000C, 0, 6, 1, 72, 0, 0)
        struct.pack_into("<II", data, 32, LC_SEGMENT_64, 72)
        data[40:56] = b"__DATA_CONST".ljust(16, b"\0")
        patched, sections, tuples = disable_interposing(bytes(data))
        self.assertEqual((patched, sections, tuples), (bytes(data), 0, 0))

    def test_rejects_misaligned_interpose_section(self):
        with self.assertRaisesRegex(ValueError, "tuple aligned"):
            disable_interposing(mach_o_with_interpose(size=17))


if __name__ == "__main__":
    unittest.main()
