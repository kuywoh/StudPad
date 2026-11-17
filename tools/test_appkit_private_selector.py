"""Regression tests for the NSApplication launch selector compatibility hooks."""

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

    def test_nsapplication_stores_effective_appearance_for_qt_kvo(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )
        start = source.index("@implementation NSApplication")
        end = source.index("\n@end", start)
        implementation = source[start:end]

        self.assertIn("id _msEffectiveAppearance;", source)
        self.assertIn("- (void)setEffectiveAppearance:(id)appearance {", implementation)
        self.assertIn("if (_msEffectiveAppearance == appearance) return;", implementation)
        self.assertIn("_msEffectiveAppearance = appearance;", implementation)
        self.assertIn('- (id)effectiveAppearance {', implementation)
        self.assertIn('NSClassFromString(@"NSAppearance")', implementation)

    def test_nsapplication_menu_alias_is_implemented_for_qt_and_kvo(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )
        start = source.index("@implementation NSApplication")
        end = source.index("@end", start)
        implementation = source[start:end]

        self.assertIn("- (void)setMenu:(id)menu { _msMainMenu = menu; }", implementation)
        self.assertIn("- (id)menu { return _msMainMenu; }", implementation)
        self.assertIn("- (void)setMainMenu:(id)menu { _msMainMenu = menu; }", implementation)
        self.assertIn("- (id)mainMenu { return _msMainMenu; }", implementation)

    def test_nsapplication_reports_no_active_modal_window_at_launch(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )
        start = source.index("@implementation NSApplication")
        end = source.index("\n@end", start)
        implementation = source[start:end]

        self.assertIn("- (NSWindow *)modalWindow;", source)
        self.assertRegex(
            implementation,
            re.compile(r"-\s*\(NSWindow \*\)\s*modalWindow\s*\{\s*return nil;\s*\}"),
        )


class MSColorCompatibilityTests(unittest.TestCase):
    def test_solid_mscolor_has_no_pattern_image(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )
        start = source.index("@implementation MSColor")
        end = source.index("\n@end", start)
        implementation = source[start:end]

        self.assertIn("- (NSInteger)type { return 0; }", implementation)
        self.assertIn(
            "- (NSString *)colorSpaceName { return (__bridge NSString *)NSDeviceRGBColorSpace; }",
            implementation,
        )
        self.assertIn(
            "NSString *spaceName = [name isKindOfClass:NSString.class] ? name : nil;",
            implementation,
        )
        self.assertIn(
            "if ([spaceName isEqualToString:(__bridge NSString *)NSPatternColorSpace]) return nil;",
            implementation,
        )
        self.assertIn("- (id)patternImage { return nil; }", implementation)


    def test_existing_nscolor_palette_methods_are_wrapped(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )
        start = source.index("static void ms_install_appkit_colors(void)")
        end = source.index("\\nstatic void ms_pump", start)
        install = source[start:end]

        self.assertIn("int wrapped = 0;", install)
        self.assertIn("class_replaceMethod(object_getClass(cls)", install)
        self.assertIn("palette[i].selector", install)
        self.assertIn("(IMP)ms_nscolor_static_color", install)


class CocoaDisplayCompatibilityTests(unittest.TestCase):
    def test_uikit_bounds_and_nsscreen_id_match_coregraphics_display(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '- (id)deviceDescription { return @{@"NSScreenNumber": @(CGMainDisplayID())}; }',
            source,
        )
        start = source.index("void studpad_guest_start(void)")
        setup = source[start : start + 700]
        self.assertIn("studpad_set_main_screen_bounds(mainScreen.bounds);", setup)
        self.assertIn("UIScreen *mainScreen = UIScreen.mainScreen;", setup)


class AppKitMenuItemCompatibilityTests(unittest.TestCase):
    def test_separator_factory_returns_a_real_separator_item(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )
        start = source.index("@implementation NSMenuItem")
        end = source.index("@end", start)
        implementation = source[start:end]

        self.assertIn("BOOL _msSeparatorItem;", source)
        self.assertIn("+ (instancetype)separatorItem {", implementation)
        self.assertIn(
            'NSMenuItem *item = [[self alloc] initWithTitle:@"" action:NULL keyEquivalent:@""];',
            implementation,
        )
        self.assertIn("item->_msSeparatorItem = YES;", implementation)
        self.assertIn("return item;", implementation)
        self.assertIn(
            "- (BOOL)isSeparatorItem { return _msSeparatorItem; }", implementation
        )

class StubReturnContractTests(unittest.TestCase):
    def test_unknown_selectors_zero_the_aarch64_return_registers(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )

        self.assertIn("__attribute__((naked)) static void ms_zero_return_imp(void)", source)
        for register in (f"x{index}" for index in range(8)):
            self.assertIn(f'"mov {register}, xzr\\n\\t"', source)
        for register in (f"d{index}" for index in range(8)):
            self.assertIn(f'"fmov {register}, xzr\\n\\t"', source)
        self.assertIn("(IMP)ms_zero_return_imp", source)
        self.assertNotIn("(IMP)ms_zero_imp", source)

    def test_nscolor_instance_resolution_does_not_cast_an_instance_to_class(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )

        start = source.index("static BOOL ms_nscolor_claim")
        end = source.index("\n}\n", start) + 3
        claim = source[start:end]
        self.assertIn("isClass ? (Class)self : object_getClass(self)", claim)
        self.assertNotIn("Class cls = (Class)self;", claim)
        self.assertIn("(IMP)ms_zero_return_imp", claim)

    def test_log_path_creates_documents_before_the_first_write(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )

        start = source.index("static NSString *studpad_log_path(void)")
        end = source.index("static void studpad_open_log(void)", start)
        log_path = source[start:end]
        self.assertIn("createDirectoryAtPath:directory", log_path)
        self.assertIn("withIntermediateDirectories:YES", log_path)


class HostDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.source = (Path(__file__).resolve().parents[1] / "app" / "starter.m").read_text(
            encoding="utf-8"
        )

    def test_signal_handler_writes_a_crash_marker_the_next_launch_can_share(self):
        start = self.source.index("static void crash_signal(")
        end = self.source.index("\n}\n", self.source.index("_exit(128 + sig)", start)) + 3
        handler = self.source[start:end]

        self.assertIn("studpad_crash_flag_path()", handler)
        self.assertIn("O_TRUNC", handler)
        self.assertIn("backtrace_symbols_fd(frames, count, flag)", handler)
        self.assertIn("studpad_log_path_c()", handler)

    def test_host_writes_documents_before_uikit_starts(self):
        start = self.source.index("static const char *studpad_documents_dir(void)")
        end = self.source.index("static NSDictionary *read_dictionary_plist", start)
        setup = self.source[start:end]

        self.assertIn('"%s/Documents"', setup)
        self.assertIn("mkdir(path, 0700)", setup)
        self.assertIn("studio.log", setup)
        self.assertIn("__attribute__((constructor))", setup)

    def test_host_exposes_a_share_log_action(self):
        self.assertIn("selector:@selector(shareLog:)", self.source)
        self.assertIn("UIActivityViewController", self.source)
        self.assertIn("popoverPresentationController.sourceRect", self.source)


if __name__ == "__main__":
    unittest.main()
