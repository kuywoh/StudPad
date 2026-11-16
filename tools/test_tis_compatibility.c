#include "TISCompatibility.h"

#include <assert.h>

int main(void) {
    CFTypeRef source = TISCopyCurrentKeyboardInputSource();
    assert(source != NULL);
    assert(CFGetTypeID(source) == CFStringGetTypeID());

    CFArrayRef languages = (CFArrayRef)TISGetInputSourceProperty(
        source, kTISPropertyInputSourceLanguages);
    assert(languages != NULL);
    assert(CFGetTypeID(languages) == CFArrayGetTypeID());
    assert(CFArrayGetCount(languages) == 1);

    CFTypeRef language = CFArrayGetValueAtIndex(languages, 0);
    assert(language != NULL);
    assert(CFGetTypeID(language) == CFStringGetTypeID());
    assert(CFEqual(language, CFSTR("en-US")));

    assert(TISGetInputSourceProperty(NULL, kTISPropertyInputSourceLanguages) == NULL);
    assert(TISGetInputSourceProperty(source, kTISPropertyUnicodeKeyLayoutData) == NULL);
    assert(TISCopyInputMethodKeyboardLayoutOverride() == NULL);

    assert(CFEqual(NSPasteboardNameDrag, CFSTR("NSDragPboard")));
    assert(CFEqual(NSPasteboardTypeString, CFSTR("public.utf8-plain-text")));

    CFRelease(source);

    void *pasteboard = (void *)1;
    int32_t status = PasteboardCreate(CFSTR("general"), &pasteboard);
    assert(status != 0);
    assert(pasteboard == NULL);
    assert(PasteboardSetPromiseKeeper(NULL, NULL, NULL) != 0);
    return 0;
}
