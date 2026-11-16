"""Regression checks for Objective-C classes the shim must leave to iOS Foundation."""

import tempfile
import unittest
from pathlib import Path

from tools.plan_shim import FOUNDATION_RUNTIME_CLASSES, write_objc_stubs


class FoundationRuntimeClassTests(unittest.TestCase):
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
