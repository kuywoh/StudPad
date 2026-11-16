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

    def test_nsapplication_reports_no_active_modal_window_at_launch(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )
        start = source.index("@implementation NSApplication")
        end = source.index("\\n@end", start)
        implementation = source[start:end]

        self.assertIn("- (NSWindow *)modalWindow;", source)
        self.assertRegex(
            implementation,
            re.compile(r"-\\s*\\(NSWindow \\*\\)\\s*modalWindow\\s*\\{\\s*return nil;\\s*\\}"),
        )


if __name__ == "__main__":
    unittest.main()
