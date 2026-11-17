"""Regression checks for Objective-C classes and ABI-sensitive shim symbols."""

import tempfile
import unittest
from pathlib import Path

from tools.plan_shim import (
    FOUNDATION_RUNTIME_CLASSES,
    GLOBAL_SHAPED,
    GLOBAL_SHAPED_EXCEPTIONS,
    STATUS_RETURN_SYMBOLS,
    TYPED_DATA_SYMBOLS,
    TYPED_SHIM_SYMBOLS,
    UNSAFE_ABI_SYMBOLS,
    unsafe_stub_symbols,
    write_c_stubs,
    write_objc_stubs,
)

ROOT = Path(__file__).resolve().parents[1]


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
            "_NSDeviceRGBColorSpace",
            "_NSDeviceSize",
            "_kUTTagClassOSType",
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


class UnsafeStubTests(unittest.TestCase):
    def test_known_data_symbols_are_refused_as_function_stubs(self):
        symbols = sorted(TYPED_DATA_SYMBOLS)
        self.assertEqual(unsafe_stub_symbols(symbols), symbols)

    def test_struct_returning_symbols_are_refused_as_function_stubs(self):
        symbols = sorted(UNSAFE_ABI_SYMBOLS)
        self.assertEqual(unsafe_stub_symbols(symbols), symbols)

    def test_unknown_global_shapes_are_refused(self):
        symbols = ["_NSFutureNotification", "_kFutureFrameworkKey", "_NSFontWeightFuture"]
        self.assertEqual(unsafe_stub_symbols(symbols), sorted(symbols))

    def test_function_shaped_exceptions_are_not_refused(self):
        self.assertEqual(unsafe_stub_symbols(sorted(GLOBAL_SHAPED_EXCEPTIONS)), [])
        self.assertEqual(
            unsafe_stub_symbols(
                [
                    "_TISGetInputSourceProperty",
                    "_CGDisplayCopyDisplayMode",
                    "_NSColorSpaceFromDepth",
                ]
            ),
            [],
        )

    def test_every_typed_symbol_has_a_source_definition(self):
        for symbol, relative_path in TYPED_SHIM_SYMBOLS.items():
            with self.subTest(symbol=symbol):
                source = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn(symbol[1:], source)


class StatusStubTests(unittest.TestCase):
    @staticmethod
    def _groups(functions):
        return {
            "functions": functions,
            "classes": [],
            "ivars": [],
            "ehtypes": [],
            "asm": [],
        }

    def test_status_returning_symbols_report_failure(self):
        symbol = "_IOServiceAddMatchingNotification"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "stubs.c"
            write_c_stubs(self._groups([symbol]), str(output))
            contents = output.read_text(encoding="utf-8")

        self.assertIn(f"int32_t {symbol[1:]}(void)", contents)
        self.assertIn("return -1;", contents)
        self.assertNotIn(f"void *{symbol[1:]}(void)", contents)

    def test_every_curated_status_symbol_is_a_c_identifier(self):
        symbols = sorted(STATUS_RETURN_SYMBOLS)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "stubs.c"
            write_c_stubs(self._groups(symbols), str(output))
            contents = output.read_text(encoding="utf-8")

        for symbol in symbols:
            with self.subTest(symbol=symbol):
                self.assertIn(f"int32_t {symbol[1:]}(void)", contents)
        self.assertNotIn("void *", contents)
        self.assertEqual(contents.count("return -1;"), len(symbols))

    def test_other_functions_still_get_pointer_stubs(self):
        symbol = "_CGDisplayCopyDisplayMode"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "stubs.c"
            write_c_stubs(self._groups([symbol]), str(output))
            contents = output.read_text(encoding="utf-8")

        self.assertIn(f"void *{symbol[1:]}(void)", contents)
        self.assertIn(f'return studpad_stub("{symbol[1:]}");', contents)

    def test_status_symbols_do_not_need_typed_shims(self):
        self.assertEqual(set(STATUS_RETURN_SYMBOLS) & set(TYPED_SHIM_SYMBOLS), set())
        self.assertEqual(unsafe_stub_symbols(sorted(STATUS_RETURN_SYMBOLS)), [])


if __name__ == "__main__":
    unittest.main()
