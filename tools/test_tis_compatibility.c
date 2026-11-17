#include "TISCompatibility.h"

#include <assert.h>

static void expect_string_property(CFTypeRef source, CFStringRef key) {
    CFTypeRef value = TISGetInputSourceProperty(source, key);
    assert(value != NULL);
    assert(CFGetTypeID(value) == CFStringGetTypeID());
    assert(CFStringGetLength((CFStringRef)value) > 0);
}

int main(void) {
    // QCocoaInputContext::updateLocale() calls CFArrayGetCount on this result without checking for
    // NULL. The exact crash path from build 63 is exercised here.
    CFTypeRef source = TISCopyCurrentKeyboardInputSource();
    assert(source != NULL);
    assert(CFGetTypeID(source) == CFDictionaryGetTypeID());

    CFArrayRef languages = (CFArrayRef)TISGetInputSourceProperty(
        source, kTISPropertyInputSourceLanguages);
    assert(languages != NULL);
    assert(CFGetTypeID(languages) == CFArrayGetTypeID());
    assert(CFArrayGetCount(languages) == 1);

    CFTypeRef language = CFArrayGetValueAtIndex(languages, 0);
    assert(language != NULL);
    assert(CFGetTypeID(language) == CFStringGetTypeID());
    assert(CFEqual(language, CFSTR("en-US")));

    expect_string_property(source, kTISPropertyInputSourceID);
    expect_string_property(source, kTISPropertyInputSourceType);
    expect_string_property(source, kTISPropertyInputSourceCategory);
    expect_string_property(source, kTISPropertyLocalizedName);
    expect_string_property(source, kTISPropertyBundleID);
    expect_string_property(source, kTISPropertyInputModeID);

    CFTypeRef enabled = TISGetInputSourceProperty(source, kTISPropertyInputSourceIsEnabled);
    assert(enabled != NULL);
    assert(CFGetTypeID(enabled) == CFBooleanGetTypeID());
    assert(CFBooleanGetValue((CFBooleanRef)enabled));

    assert(TISGetInputSourceProperty(NULL, kTISPropertyInputSourceLanguages) == NULL);
    assert(TISGetInputSourceProperty(source, NULL) == NULL);
    assert(TISGetInputSourceProperty(source, kTISPropertyUnicodeKeyLayoutData) == NULL);
    assert(TISCopyInputMethodKeyboardLayoutOverride() == NULL);

    // The second entry point must also return a retained object with the language property.
    CFTypeRef layout = TISCopyCurrentKeyboardLayoutInputSource();
    assert(layout != NULL);
    assert(CFGetTypeID(layout) == CFDictionaryGetTypeID());
    assert(TISGetInputSourceProperty(layout, kTISPropertyInputSourceLanguages) == languages);
    CFRelease(layout);

    assert(CFGetTypeID(kTISPropertyInputSourceLanguages) == CFStringGetTypeID());
    assert(CFGetTypeID(kTISPropertyUnicodeKeyLayoutData) == CFStringGetTypeID());
    assert(CFGetTypeID(kTISNotifySelectedKeyboardInputSourceChanged) == CFStringGetTypeID());
    assert(CFEqual(NSPasteboardNameDrag, CFSTR("NSDragPboard")));
    assert(CFEqual(NSPasteboardTypeString, CFSTR("public.utf8-plain-text")));

    CFRelease(source);

    // PasteboardCreate must fail *and* clear the output. Qt logs a creation error only when the
    // status is non-zero; a null pasteboard reported as success is what makes it use a dead handle.
    CFTypeRef pasteboard = (CFTypeRef)1;
    int32_t status = PasteboardCreate(CFSTR("general"), &pasteboard);
    assert(status == STUDPAD_PASTEBOARD_UNAVAILABLE);
    assert(pasteboard == NULL);
    assert(PasteboardCreate(CFSTR("general"), NULL) == STUDPAD_PASTEBOARD_UNAVAILABLE);

    assert(PasteboardClear(NULL) == STUDPAD_PASTEBOARD_UNAVAILABLE);
    assert(PasteboardResolvePromises(NULL) == STUDPAD_PASTEBOARD_UNAVAILABLE);
    assert(PasteboardSynchronize(NULL) == STUDPAD_PASTEBOARD_UNAVAILABLE);
    assert(PasteboardSetPromiseKeeper(NULL, NULL, NULL) == STUDPAD_PASTEBOARD_UNAVAILABLE);

    CFDataRef data = (CFDataRef)1;
    assert(PasteboardCopyItemFlavorData(NULL, 0, NULL, &data) == STUDPAD_PASTEBOARD_UNAVAILABLE);
    assert(data == NULL);

    CFArrayRef flavors = (CFArrayRef)1;
    assert(PasteboardCopyItemFlavors(NULL, 0, &flavors) == STUDPAD_PASTEBOARD_UNAVAILABLE);
    assert(flavors == NULL);

    CFStringRef name = (CFStringRef)1;
    assert(PasteboardCopyName(NULL, &name) == STUDPAD_PASTEBOARD_UNAVAILABLE);
    assert(name == NULL);

    unsigned long count = 42;
    assert(PasteboardGetItemCount(NULL, &count) == STUDPAD_PASTEBOARD_UNAVAILABLE);
    assert(count == 0);

    uint32_t flags = 42;
    assert(PasteboardGetItemFlavorFlags(NULL, 0, NULL, &flags) == STUDPAD_PASTEBOARD_UNAVAILABLE);
    assert(flags == 0);

    uint32_t item = 42;
    assert(PasteboardGetItemIdentifier(NULL, 0, &item) == STUDPAD_PASTEBOARD_UNAVAILABLE);
    assert(item == 0);

    assert(PasteboardPutItemFlavor(NULL, 0, NULL, NULL, 0) == STUDPAD_PASTEBOARD_UNAVAILABLE);
    return 0;
}
