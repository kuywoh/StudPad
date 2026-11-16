"""Regression tests for parsing exported symbols in SDK text-based stubs."""

import unittest

from tools.check_binds import tbd_symbols


class TBDExportTests(unittest.TestCase):
    def test_multiline_objc_class_list_exports_classes_and_metaclasses(self):
        tbd = """\
exports:
  - targets: [ arm64-ios ]
    objc-classes: [ NSArray,
                    NSMutableArray,
                    _PrivateFoundationClass ]
"""
        symbols = tbd_symbols(tbd)
        for name in ("NSArray", "NSMutableArray", "_PrivateFoundationClass"):
            with self.subTest(name=name):
                self.assertIn(f"_OBJC_CLASS_$_{name}", symbols)
                self.assertIn(f"_OBJC_METACLASS_$_{name}", symbols)

    def test_wrapped_symbol_list_is_still_parsed(self):
        tbd = """\
exports:
  - targets: [ arm64-ios ]
    symbols: [ _firstExport,
               _secondExport ]
"""
        self.assertTrue({"_firstExport", "_secondExport"}.issubset(tbd_symbols(tbd)))


if __name__ == "__main__":
    unittest.main()
