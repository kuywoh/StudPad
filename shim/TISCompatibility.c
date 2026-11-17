#include "TISCompatibility.h"

#include <pthread.h>

const CFStringRef kTISPropertyInputSourceLanguages =
    CFSTR("TISPropertyInputSourceLanguages");
const CFStringRef kTISPropertyInputSourceID = CFSTR("TISPropertyInputSourceID");
const CFStringRef kTISPropertyInputSourceType = CFSTR("TISPropertyInputSourceType");
const CFStringRef kTISPropertyInputSourceCategory = CFSTR("TISPropertyInputSourceCategory");
const CFStringRef kTISPropertyInputSourceIsEnabled = CFSTR("TISPropertyInputSourceIsEnabled");
const CFStringRef kTISPropertyInputSourceIsSelected = CFSTR("TISPropertyInputSourceIsSelected");
const CFStringRef kTISPropertyInputSourceIsSelectCapable =
    CFSTR("TISPropertyInputSourceIsSelectCapable");
const CFStringRef kTISPropertyInputSourceIsASCIICapable =
    CFSTR("TISPropertyInputSourceIsASCIICapable");
const CFStringRef kTISPropertyLocalizedName = CFSTR("TISPropertyLocalizedName");
const CFStringRef kTISPropertyBundleID = CFSTR("TISPropertyBundleID");
const CFStringRef kTISPropertyInputModeID = CFSTR("TISPropertyInputModeID");
const CFStringRef kTISPropertyUnicodeKeyLayoutData =
    CFSTR("TISPropertyUnicodeKeyLayoutData");
const CFStringRef kTISCategoryKeyboardInputSource = CFSTR("TISCategoryKeyboardInputSource");
const CFStringRef kTISNotifySelectedKeyboardInputSourceChanged =
    CFSTR("com.apple.Carbon.TISNotifySelectedKeyboardInputSourceChanged");
const CFStringRef NSPasteboardNameDrag = CFSTR("NSDragPboard");
const CFStringRef NSPasteboardTypeString = CFSTR("public.utf8-plain-text");

static pthread_once_t gInputSourceOnce = PTHREAD_ONCE_INIT;
static CFArrayRef gLanguageArray;
static CFDictionaryRef gInputSource;

static void create_input_source(void) {
    const void *languages[] = { CFSTR("en-US") };
    gLanguageArray =
        CFArrayCreate(kCFAllocatorDefault, languages, 1, &kCFTypeArrayCallBacks);
    if (!gLanguageArray) return;

    const void *keys[] = {
        kTISPropertyInputSourceLanguages,
        kTISPropertyInputSourceID,
        kTISPropertyInputSourceType,
        kTISPropertyInputSourceCategory,
        kTISPropertyInputSourceIsEnabled,
        kTISPropertyInputSourceIsSelected,
        kTISPropertyInputSourceIsSelectCapable,
        kTISPropertyInputSourceIsASCIICapable,
        kTISPropertyLocalizedName,
        kTISPropertyBundleID,
        kTISPropertyInputModeID,
    };
    const void *values[] = {
        gLanguageArray,
        CFSTR("com.kuywoh.StudPad.keyboard.en-US"),
        CFSTR("TISTypeKeyboardLayout"),
        kTISCategoryKeyboardInputSource,
        kCFBooleanTrue,
        kCFBooleanTrue,
        kCFBooleanTrue,
        kCFBooleanTrue,
        CFSTR("English (US)"),
        CFSTR("com.kuywoh.StudPad"),
        CFSTR("com.kuywoh.StudPad.keyboard.en-US"),
    };
    gInputSource = CFDictionaryCreate(kCFAllocatorDefault, keys, values,
                                      (CFIndex)(sizeof keys / sizeof keys[0]),
                                      &kCFTypeDictionaryKeyCallBacks,
                                      &kCFTypeDictionaryValueCallBacks);
}

static CFTypeRef current_input_source(void) {
    (void)pthread_once(&gInputSourceOnce, create_input_source);
    return gInputSource;
}

static CFArrayRef current_language_array(void) {
    (void)current_input_source();
    return gLanguageArray;
}

CFTypeRef TISCopyCurrentKeyboardInputSource(void) {
    // Qt owns a reference to a TISCopy result and releases it, so return +1. The dictionary is a
    // valid, immutable input-source object; it is also the shape TISGetInputSourceProperty reads.
    CFTypeRef source = current_input_source();
    return CFRetain(source ? source : CFSTR("com.kuywoh.StudPad.keyboard.en-US"));
}

CFTypeRef TISCopyCurrentKeyboardLayoutInputSource(void) {
    return TISCopyCurrentKeyboardInputSource();
}

CFTypeRef TISCopyInputMethodKeyboardLayoutOverride(void) {
    // No input-method override is installed.
    return NULL;
}

CFTypeRef TISGetInputSourceProperty(CFTypeRef source, CFStringRef property) {
    if (!source || !property) return NULL;
    if (CFGetTypeID(property) != CFStringGetTypeID()) return NULL;

    if (CFGetTypeID(source) == CFDictionaryGetTypeID())
        return CFDictionaryGetValue((CFDictionaryRef)source, property);

    // The fallback source is a plain CFString if the dictionary could not be allocated. Answer the
    // properties Qt asks for; everything else remains NULL.
    if (CFGetTypeID(source) != CFStringGetTypeID()) return NULL;
    if (CFEqual(property, kTISPropertyInputSourceLanguages)) return current_language_array();
    if (CFEqual(property, kTISPropertyLocalizedName)) return CFSTR("English (US)");
    if (CFEqual(property, kTISPropertyInputSourceID))
        return CFSTR("com.kuywoh.StudPad.keyboard.en-US");
    return NULL;
}

int32_t PasteboardCreate(CFStringRef name, CFTypeRef *pasteboard) {
    (void)name;
    if (pasteboard) *pasteboard = NULL;
    return STUDPAD_PASTEBOARD_UNAVAILABLE;
}

int32_t PasteboardClear(CFTypeRef pasteboard) {
    (void)pasteboard;
    return STUDPAD_PASTEBOARD_UNAVAILABLE;
}

int32_t PasteboardCopyItemFlavorData(CFTypeRef pasteboard, uint32_t itemID,
                                     CFStringRef flavorType, CFDataRef *data) {
    (void)pasteboard;
    (void)itemID;
    (void)flavorType;
    if (data) *data = NULL;
    return STUDPAD_PASTEBOARD_UNAVAILABLE;
}

int32_t PasteboardCopyItemFlavors(CFTypeRef pasteboard, uint32_t itemID, CFArrayRef *flavors) {
    (void)pasteboard;
    (void)itemID;
    if (flavors) *flavors = NULL;
    return STUDPAD_PASTEBOARD_UNAVAILABLE;
}

int32_t PasteboardCopyName(CFTypeRef pasteboard, CFStringRef *name) {
    (void)pasteboard;
    if (name) *name = NULL;
    return STUDPAD_PASTEBOARD_UNAVAILABLE;
}

int32_t PasteboardGetItemCount(CFTypeRef pasteboard, unsigned long *count) {
    (void)pasteboard;
    if (count) *count = 0;
    return STUDPAD_PASTEBOARD_UNAVAILABLE;
}

int32_t PasteboardGetItemFlavorFlags(CFTypeRef pasteboard, uint32_t itemID,
                                     CFStringRef flavorType, uint32_t *flags) {
    (void)pasteboard;
    (void)itemID;
    (void)flavorType;
    if (flags) *flags = 0;
    return STUDPAD_PASTEBOARD_UNAVAILABLE;
}

int32_t PasteboardGetItemIdentifier(CFTypeRef pasteboard, long index, uint32_t *itemID) {
    (void)pasteboard;
    (void)index;
    if (itemID) *itemID = 0;
    return STUDPAD_PASTEBOARD_UNAVAILABLE;
}

int32_t PasteboardPutItemFlavor(CFTypeRef pasteboard, uint32_t itemID, CFStringRef flavorType,
                                CFDataRef data, uint32_t flags) {
    (void)pasteboard;
    (void)itemID;
    (void)flavorType;
    (void)data;
    (void)flags;
    return STUDPAD_PASTEBOARD_UNAVAILABLE;
}

int32_t PasteboardResolvePromises(CFTypeRef pasteboard) {
    (void)pasteboard;
    return STUDPAD_PASTEBOARD_UNAVAILABLE;
}

int32_t PasteboardSetPromiseKeeper(CFTypeRef pasteboard, void *keeper, void *context) {
    (void)pasteboard;
    (void)keeper;
    (void)context;
    return STUDPAD_PASTEBOARD_UNAVAILABLE;
}

int32_t PasteboardSynchronize(CFTypeRef pasteboard) {
    (void)pasteboard;
    return STUDPAD_PASTEBOARD_UNAVAILABLE;
}
