#ifndef STUDPAD_TIS_COMPATIBILITY_H
#define STUDPAD_TIS_COMPATIBILITY_H

#include <CoreFoundation/CoreFoundation.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

extern const CFStringRef kTISPropertyInputSourceLanguages;
extern const CFStringRef kTISPropertyUnicodeKeyLayoutData;
extern const CFStringRef kTISNotifySelectedKeyboardInputSourceChanged;
extern const CFStringRef NSPasteboardNameDrag;
extern const CFStringRef NSPasteboardTypeString;

CFTypeRef TISCopyCurrentKeyboardInputSource(void);
CFTypeRef TISCopyCurrentKeyboardLayoutInputSource(void);
CFTypeRef TISCopyInputMethodKeyboardLayoutOverride(void);
CFTypeRef TISGetInputSourceProperty(CFTypeRef source, CFStringRef property);

// Clipboard support is intentionally unavailable. Return an OSStatus failure and initialize any
// output so Qt cannot mistake a null pasteboard for a successfully created one.
int32_t PasteboardCreate(CFStringRef name, void **pasteboard);
int32_t PasteboardSetPromiseKeeper(void *pasteboard, void *keeper, void *context);

#ifdef __cplusplus
}
#endif

#endif
