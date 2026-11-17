#ifndef STUDPAD_LEGACY_COMPATIBILITY_H
#define STUDPAD_LEGACY_COMPATIBILITY_H

#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CGBase.h>
#include <CoreGraphics/CGError.h>
#include <CoreGraphics/CGGeometry.h>
#include <mach/mach.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// AppKit globals that the guest loads as data. A generated function under one of these names would
// hand Studio the function's machine code where it expects an object, CGFloat or NSSize.
extern const CFStringRef NSAppearanceNameAqua;
extern const CFStringRef NSAppearanceNameDarkAqua;
extern const CFStringRef NSDeviceCMYKColorSpace;
extern const CFStringRef NSDeviceRGBColorSpace;
extern const CFStringRef NSNamedColorSpace;
extern const CFStringRef NSPatternColorSpace;

extern const CGFloat NSFontWeightUltraLight;
extern const CGFloat NSFontWeightThin;
extern const CGFloat NSFontWeightLight;
extern const CGFloat NSFontWeightRegular;
extern const CGFloat NSFontWeightMedium;
extern const CGFloat NSFontWeightSemibold;
extern const CGFloat NSFontWeightBold;
extern const CGFloat NSFontWeightHeavy;
extern const CGFloat NSFontWeightBlack;

// NSSize is a pair of CGFloats on every 64-bit Apple target. Zero is the only value this shim can
// honestly report for a device size it does not measure.
extern const CGSize NSDeviceSize;

// Carbon/Framework globals, kept as data for the same reason as the AppKit ones above.
extern const mach_port_t kIOMasterPortDefault;
extern const CFStringRef kDADiskDescriptionDeviceModelKey;
extern const CFStringRef kSecImportExportKeychain;
extern const CFStringRef kUTTagClassOSType;

// Typed display/CV shims. The generated stub returns a pointer in x0, which is not a valid
// CGRect/CGSize/CGPoint return, and leaves output pointers untouched even when it reports success.
CGRect CGDisplayBounds(uint32_t display);
CGSize CGDisplayScreenSize(uint32_t display);
double CGDisplayModeGetRefreshRate(void *mode);
CGPoint CGEventGetLocation(void *event);
CGError CGGetDisplaysWithRect(CGRect rect, uint32_t maxDisplays, uint32_t *displays,
                              uint32_t *count);
CGError CGGetOnlineDisplayList(uint32_t maxDisplays, uint32_t *displays, uint32_t *count);
int32_t CVDisplayLinkCreateWithCGDisplay(uint32_t display, void **displayLinkOut);
int32_t CVDisplayLinkSetOutputCallback(void *displayLink, void *callback, void *context);
int32_t CVDisplayLinkStart(void *displayLink);
int32_t CVDisplayLinkStop(void *displayLink);
uint32_t CVDisplayLinkIsRunning(void *displayLink);
void CVDisplayLinkRelease(void *displayLink);
CGRect *HIShapeGetBounds(void *shape, CGRect *bounds);
double PMPaperGetHeight(void *paper);
double PMPaperGetWidth(void *paper);

#ifdef __cplusplus
}
#endif

#endif
