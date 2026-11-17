#ifndef STUDPAD_TIS_COMPATIBILITY_H
#define STUDPAD_TIS_COMPATIBILITY_H

#include <CoreFoundation/CoreFoundation.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Text Input Sources constants are real CFString data, not generated functions: the guest loads
// the pointer out of the symbol and passes it to TISGetInputSourceProperty/CFEqual.
extern const CFStringRef kTISPropertyInputSourceLanguages;
extern const CFStringRef kTISPropertyInputSourceID;
extern const CFStringRef kTISPropertyInputSourceType;
extern const CFStringRef kTISPropertyInputSourceCategory;
extern const CFStringRef kTISPropertyInputSourceIsEnabled;
extern const CFStringRef kTISPropertyInputSourceIsSelected;
extern const CFStringRef kTISPropertyInputSourceIsSelectCapable;
extern const CFStringRef kTISPropertyInputSourceIsASCIICapable;
extern const CFStringRef kTISPropertyLocalizedName;
extern const CFStringRef kTISPropertyBundleID;
extern const CFStringRef kTISPropertyInputModeID;
extern const CFStringRef kTISPropertyUnicodeKeyLayoutData;
extern const CFStringRef kTISCategoryKeyboardInputSource;
extern const CFStringRef kTISNotifySelectedKeyboardInputSourceChanged;

// Pasteboard name/type globals are also data. Qt's cocoa plugin binds NSPasteboardNameDrag and
// NSPasteboardTypeString through the shim.
extern const CFStringRef NSPasteboardNameDrag;
extern const CFStringRef NSPasteboardTypeString;

// TISCopy* returns a +1 Core Foundation object. TISGetInputSourceProperty returns a borrowed
// property whose type depends on the key: CFArray for languages, CFString for names/IDs, CFBoolean
// for flags, and CFData only when a real Unicode layout is available. The language array is always
// non-NULL so QCocoaInputContext::updateLocale() can call CFArrayGetCount() safely.
CFTypeRef TISCopyCurrentKeyboardInputSource(void);
CFTypeRef TISCopyCurrentKeyboardLayoutInputSource(void);
CFTypeRef TISCopyInputMethodKeyboardLayoutOverride(void);
CFTypeRef TISGetInputSourceProperty(CFTypeRef source, CFStringRef property);

// Carbon pasteboard support is intentionally unavailable. Every entry point reports an OSStatus
// failure; the Copy/Create-style entry points first clear their output so Qt cannot mistake a null
// pasteboard for a successfully created one.
enum { STUDPAD_PASTEBOARD_UNAVAILABLE = -4 /* unimpErr */ };

int32_t PasteboardCreate(CFStringRef name, CFTypeRef *pasteboard);
int32_t PasteboardClear(CFTypeRef pasteboard);
int32_t PasteboardCopyItemFlavorData(CFTypeRef pasteboard, uint32_t itemID,
                                     CFStringRef flavorType, CFDataRef *data);
int32_t PasteboardCopyItemFlavors(CFTypeRef pasteboard, uint32_t itemID, CFArrayRef *flavors);
int32_t PasteboardCopyName(CFTypeRef pasteboard, CFStringRef *name);
int32_t PasteboardGetItemCount(CFTypeRef pasteboard, unsigned long *count);
int32_t PasteboardGetItemFlavorFlags(CFTypeRef pasteboard, uint32_t itemID,
                                     CFStringRef flavorType, uint32_t *flags);
int32_t PasteboardGetItemIdentifier(CFTypeRef pasteboard, long index, uint32_t *itemID);
int32_t PasteboardPutItemFlavor(CFTypeRef pasteboard, uint32_t itemID, CFStringRef flavorType,
                                CFDataRef data, uint32_t flags);
int32_t PasteboardResolvePromises(CFTypeRef pasteboard);
int32_t PasteboardSetPromiseKeeper(CFTypeRef pasteboard, void *keeper, void *context);
int32_t PasteboardSynchronize(CFTypeRef pasteboard);

#ifdef __cplusplus
}
#endif

#endif
