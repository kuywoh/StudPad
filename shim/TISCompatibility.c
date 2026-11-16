#include "TISCompatibility.h"

#include <pthread.h>

const CFStringRef kTISPropertyInputSourceLanguages =
    CFSTR("TISPropertyInputSourceLanguages");
const CFStringRef kTISPropertyUnicodeKeyLayoutData =
    CFSTR("TISPropertyUnicodeKeyLayoutData");
const CFStringRef kTISNotifySelectedKeyboardInputSourceChanged =
    CFSTR("com.apple.Carbon.TISNotifySelectedKeyboardInputSourceChanged");
const CFStringRef NSPasteboardNameDrag = CFSTR("NSDragPboard");
const CFStringRef NSPasteboardTypeString = CFSTR("public.utf8-plain-text");

static pthread_once_t gLanguageArrayOnce = PTHREAD_ONCE_INIT;
static CFArrayRef gLanguageArray;

static void create_language_array(void) {
    const void *languages[] = { CFSTR("en-US") };
    gLanguageArray = CFArrayCreate(kCFAllocatorDefault, languages, 1, &kCFTypeArrayCallBacks);
}

static CFArrayRef current_language_array(void) {
    (void)pthread_once(&gLanguageArrayOnce, create_language_array);
    return gLanguageArray;
}

CFTypeRef TISCopyCurrentKeyboardInputSource(void) {
    // Qt releases the Copy result, so return a retained, valid Core Foundation object.
    return CFRetain(CFSTR("com.kuywoh.StudPad.keyboard.en-US"));
}

CFTypeRef TISCopyCurrentKeyboardLayoutInputSource(void) {
    return TISCopyCurrentKeyboardInputSource();
}

CFTypeRef TISCopyInputMethodKeyboardLayoutOverride(void) {
    return NULL;
}

CFTypeRef TISGetInputSourceProperty(CFTypeRef source, CFStringRef property) {
    if (!source || !property) return NULL;

    if (CFEqual(property, kTISPropertyInputSourceLanguages)) {
        return current_language_array();
    }
    if (CFEqual(property, CFSTR("TISPropertyLocalizedName"))) {
        return CFSTR("English (US)");
    }

    // A fabricated Unicode layout would make Qt's key translator read invalid bytes.
    return NULL;
}

int32_t PasteboardCreate(CFStringRef name, void **pasteboard) {
    (void)name;
    if (pasteboard) *pasteboard = NULL;
    return -4; // Carbon unimpErr: this shim does not provide a host pasteboard.
}

int32_t PasteboardSetPromiseKeeper(void *pasteboard, void *keeper, void *context) {
    (void)pasteboard;
    (void)keeper;
    (void)context;
    return -4;
}
