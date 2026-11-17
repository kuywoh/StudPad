"""Regression tests for parsing exported symbols in SDK text-based stubs."""

import unittest

from tools.check_binds import is_allocator_symbol, tbd_symbols


class AllocatorBindingTests(unittest.TestCase):
    def test_c_and_cpp_allocator_imports_are_reported(self):
        for symbol in ("_malloc", "_free", "_realloc", "__Znwm", "__ZdlPv", "_mi_malloc"):
            with self.subTest(symbol=symbol):
                self.assertTrue(is_allocator_symbol(symbol))

    def test_non_allocator_cpp_symbols_are_not_reported(self):
        self.assertFalse(is_allocator_symbol("_ZN12QKeySequenceD1Ev"))


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
