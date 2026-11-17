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
        end = source.index("static void ms_pump", start)
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


class AppKitAlertCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )
        start = self.source.index("@implementation NSAlert")
        self.alert = self.source[start : self.source.index("\n@end", start)]

    def test_nsalert_is_a_real_class_implementing_the_dialog_api(self):
        # A generated MSStubObject answers one missing setter at a time; the callers configure the
        # whole dialog, so the class has to implement the whole surface they use.
        self.assertIn("@interface NSAlert : MSStubObject {", self.source)
        for selector in (
            "- (void)setMessageText:(NSString *)text {",
            "- (NSString *)messageText { return _msMessageText; }",
            "- (void)setInformativeText:(NSString *)text {",
            "- (void)setAlertStyle:(NSInteger)style { _msAlertStyle = style; }",
            "- (MSAlertButton *)addButtonWithTitle:(NSString *)title {",
            "- (NSArray *)buttons {",
            "- (NSInteger)runModal {",
            "- (void)beginSheetModalForWindow:(id)window completionHandler:(void (^)(NSInteger))handler {",
        ):
            self.assertIn(selector, self.alert)

    def test_run_modal_answers_with_the_default_button_instead_of_blocking(self):
        # Studio's launch must not wait for a tap Qt never asks the user for.
        self.assertIn("return MS_ALERT_FIRST_BUTTON;", self.alert)
        self.assertIn("#define MS_ALERT_FIRST_BUTTON 1000", self.source)
        run_modal = self.alert[
            self.alert.index("- (NSInteger)runModal {") : self.alert.index("beginSheetModalForWindow")
        ]
        self.assertNotIn("ms_pump", run_modal)
        self.assertNotIn("while", run_modal)

    def test_every_alert_is_logged_with_its_text_and_caller(self):
        # What build 97 could not answer: what the dialog said, and who showed it.
        self.assertIn(r'message=\"%@\" informative=\"%@\"', self.alert)
        self.assertIn("[titles componentsJoinedByString:@\" | \"]", self.alert)
        self.assertIn("ms_describe_caller(caller, sizeof caller);", self.alert)
        self.assertIn('ms_log_alert(@"runModal", [self ms_summaryFor:@"runModal"]);', self.alert)
        # A storm of dialogs is counted the same way a repeated miss is.
        self.assertIn("static void ms_log_alert(NSString *action, NSString *summary) {", self.source)
        self.assertIn("if (index <= MS_ALERT_SUMMARIES) {", self.source)

    def test_dialog_setters_and_misses_are_counted_not_repeated(self):
        self.assertIn("static void ms_log_event(const char *key, NSString *detail) {", self.source)
        self.assertIn("static int ms_event_count(const char *key, long *total) {", self.source)
        self.assertIn("static void ms_flush_event_counts(void) {", self.source)
        self.assertIn('ms_log_event("[alert] -[NSAlert setMessageText:]"', self.alert)
        self.assertIn('ms_log_event("[alert] -[NSAlert addButtonWithTitle:]"', self.alert)
        # Every place that used to print a miss line has to go through the counted path.
        claim = self.source[self.source.index("+ (BOOL)ms_claim:(") :]
        claim = claim[: claim.index("\n}")]
        self.assertIn("ms_log_event(key, nil);", claim)
        self.assertNotIn('studpad_log("[miss]', self.source)
        for message in ("repeated %ld times", "repeated %ld time(s) in total"):
            self.assertIn(message, self.source)

    def test_a_silent_end_still_says_how_the_process_ended(self):
        self.assertIn("atexit(ms_log_atexit_marker);", self.source)
        self.assertIn('studpad_log("[shim] exit marker: exit(%d) called from Studio", status);',
                      self.source)
        self.assertIn("{(const void *)ms_exit, (const void *)exit},", self.source)
        self.assertIn("returned %d (stub calls: %ld)", self.source)

    def test_screen_geometry_is_reported_and_compatibility_mode_is_named(self):
        self.assertIn("static void ms_log_screen_geometry(void) {", self.source)
        self.assertIn("UIScreen bounds %.0fx%.0f pt, native %.0fx%.0f px, scale %.2f/%.2f",
                      self.source)
        self.assertIn("[appKitScreen backingScaleFactor]", self.source)
        self.assertIn("iPhone compatibility", self.source)
        self.assertIn("ms_log_screen_geometry();", self.source)


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


class QtPlatformThemeStartupTests(unittest.TestCase):
    def test_cocoa_window_backend_uses_generic_theme(self):
        source = (Path(__file__).resolve().parents[1] / "shim" / "MacShim.m").read_text(
            encoding="utf-8"
        )
        start = source.index("void studpad_guest_start(void)")
        setup = source[start : source.index('uint32_t before = _dyld_image_count();', start)]

        self.assertIn('setenv("QT_QPA_PLATFORM", platform.UTF8String, 1);', setup)
        self.assertIn('setenv("QT_QPA_PLATFORMTHEME", "generic", 1);', setup)
        self.assertIn("theme: generic (avoids QCocoaTheme palette)", setup)


if __name__ == "__main__":
    unittest.main()
