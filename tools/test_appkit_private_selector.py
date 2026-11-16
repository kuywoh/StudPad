"""Regression test for NSApplication's Core Data selector registration hook."""

import re
import unittest
from pathlib import Path


class AppKitPrivateSelectorTests(unittest.TestCase):
    def test_nsapplication_has_typed_selector_registration_fallback(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )
        start = source.index("@implementation NSApplication")
        end = source.index("\n@end", start)
        implementation = source[start:end]

        self.assertRegex(
            implementation,
            re.compile(
                r"\+\s*\(BOOL\)\s*_classShouldAlwaysRegisterSelectorNamed:"
                r"\s*\(const char \*\)\s*\w+\s*\{"
                r"\s*\(void\)\w+\s*;\s*return NO;\s*\}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
