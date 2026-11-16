"""Regression checks for Objective-C classes the shim must leave to iOS Foundation."""

import tempfile
import unittest
from pathlib import Path

from tools.plan_shim import FOUNDATION_RUNTIME_CLASSES, GLOBAL_SHAPED, write_objc_stubs


class FoundationRuntimeClassTests(unittest.TestCase):
    def test_tis_and_appkit_constants_are_flagged_as_global_data(self):
        for symbol in (
            "_kTISPropertyInputSourceLanguages",
            "_kTISPropertyUnicodeKeyLayoutData",
            "_kTISNotifySelectedKeyboardInputSourceChanged",
            "_NSPasteboardNameDrag",
            "_NSPasteboardTypeString",
            "_NSFontWeightRegular",
            "_NSAppearanceNameAqua",
        ):
            with self.subTest(symbol=symbol):
                self.assertIsNotNone(GLOBAL_SHAPED.match(symbol))

        self.assertIsNone(GLOBAL_SHAPED.match("_TISCopyCurrentKeyboardInputSource"))

    def test_foundation_runtime_classes_are_not_generated_as_placeholders(self):
        required = {
            "NSDictionary",
            "NSData",
            "NSURL",
            "NSURLSession",
            "NSURLSessionConfiguration",
            "NSURLSessionDownloadTask",
            "NSHTTPURLResponse",
        }
        self.assertTrue(required.issubset(FOUNDATION_RUNTIME_CLASSES))

        symbols = [f"_OBJC_CLASS_$_{name}" for name in sorted(required)]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "stubs_objc.m"
            generated = write_objc_stubs({"classes": symbols}, str(output))
            self.assertEqual(generated, 0)
            contents = output.read_text(encoding="utf-8")
            for name in required:
                self.assertNotIn(f"@interface {name} : MSStubObject", contents)


if __name__ == "__main__":
    unittest.main()
