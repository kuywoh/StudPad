#include "LegacyCompatibility.h"

#include <stddef.h>
#include <stdbool.h>

// The values below are identifiers, not measurements: the guest compares them, uses them as
// dictionary keys, or passes them back to a framework. Each only has to be unique and non-NULL.
const CFStringRef NSAppearanceNameAqua = CFSTR("NSAppearanceNameAqua");
const CFStringRef NSAppearanceNameDarkAqua = CFSTR("NSAppearanceNameDarkAqua");
const CFStringRef NSDeviceCMYKColorSpace = CFSTR("NSDeviceCMYKColorSpace");
const CFStringRef NSDeviceRGBColorSpace = CFSTR("NSDeviceRGBColorSpace");
const CFStringRef NSNamedColorSpace = CFSTR("NSNamedColorSpace");
const CFStringRef NSPatternColorSpace = CFSTR("NSPatternColorSpace");

// Matching AppKit's public weights. They are CGFloat data, not functions: the guest loads the
// double out of the symbol, so a generated code stub would produce a meaningless font weight.
const CGFloat NSFontWeightUltraLight = -0.8;
const CGFloat NSFontWeightThin = -0.6;
const CGFloat NSFontWeightLight = -0.4;
const CGFloat NSFontWeightRegular = 0.0;
const CGFloat NSFontWeightMedium = 0.23;
const CGFloat NSFontWeightSemibold = 0.3;
const CGFloat NSFontWeightBold = 0.4;
const CGFloat NSFontWeightHeavy = 0.56;
const CGFloat NSFontWeightBlack = 0.62;

// AppKit's NSDeviceSize is an NSSize (two CGFloats). No display size is measured here, so report
// zero rather than putting a code pointer where the guest reads a pair of doubles.
const CGSize NSDeviceSize = {0.0, 0.0};

const mach_port_t kIOMasterPortDefault = MACH_PORT_NULL;
const CFStringRef kDADiskDescriptionDeviceModelKey = CFSTR("DADiskDescriptionDeviceModelKey");
const CFStringRef kSecImportExportKeychain = CFSTR("kSecImportExportKeychain");
const CFStringRef kUTTagClassOSType = CFSTR("com.apple.ostype");

// The Cocoa plugin requires a coherent display ID across CoreGraphics and NSScreen. iOS
// exposes the physical screen through UIKit, so the host supplies its bounds before Qt starts.
static const uint32_t STUDPAD_MAIN_DISPLAY_ID = 1;
static CGRect gMainDisplayBounds = {{0.0, 0.0}, {0.0, 0.0}};

void studpad_set_main_screen_bounds(CGRect bounds) {
    gMainDisplayBounds = CGRectIsEmpty(bounds) ? CGRectZero : CGRectStandardize(bounds);
}

uint32_t CGMainDisplayID(void) {
    return STUDPAD_MAIN_DISPLAY_ID;
}

CGRect CGDisplayBounds(uint32_t display) {
    return display == STUDPAD_MAIN_DISPLAY_ID ? gMainDisplayBounds : CGRectZero;
}

CGSize CGDisplayScreenSize(uint32_t display) {
    (void)display;
    return CGSizeZero;
}

// Returns CGFloat/double in d0, which a `void *` stub never fills.
double CGDisplayModeGetRefreshRate(void *mode) {
    (void)mode;
    return 0.0;
}

CGPoint CGEventGetLocation(void *event) {
    (void)event;
    return CGPointZero;
}

bool CGDisplayIsMain(uint32_t display) {
    return display == STUDPAD_MAIN_DISPLAY_ID;
}

bool CGDisplayIsOnline(uint32_t display) {
    return display == STUDPAD_MAIN_DISPLAY_ID;
}

uint32_t CGDisplayMirrorsDisplay(uint32_t display) {
    (void)display;
    return 0;
}

CFUUIDRef CGDisplayCreateUUIDFromDisplayID(uint32_t display) {
    if (display != STUDPAD_MAIN_DISPLAY_ID) return NULL;
    return CFUUIDCreateFromString(
        kCFAllocatorDefault, CFSTR("9ACDD54D-6B13-4F9A-A5BD-4BB19C4E8119"));
}

CGError CGGetDisplaysWithRect(CGRect rect, uint32_t maxDisplays, uint32_t *displays,
                              uint32_t *count) {
    if (!count) return kCGErrorFailure;
    *count = 0;
    if (!CGRectIntersectsRect(rect, gMainDisplayBounds)) return kCGErrorSuccess;
    *count = 1;
    if (maxDisplays > 0 && displays) displays[0] = STUDPAD_MAIN_DISPLAY_ID;
    return kCGErrorSuccess;
}

CGError CGGetOnlineDisplayList(uint32_t maxDisplays, uint32_t *displays, uint32_t *count) {
    if (!count) return kCGErrorFailure;
    *count = 1;
    if (maxDisplays > 0 && displays) displays[0] = STUDPAD_MAIN_DISPLAY_ID;
    return kCGErrorSuccess;
}

// CoreVideo's display link cannot be provided here. Return an error and clear the out parameter so
// a caller cannot treat an uninitialised pointer as a usable link.
int32_t CVDisplayLinkCreateWithCGDisplay(uint32_t display, void **displayLinkOut) {
    (void)display;
    if (displayLinkOut) *displayLinkOut = NULL;
    return -1;
}

int32_t CVDisplayLinkSetOutputCallback(void *displayLink, void *callback, void *context) {
    (void)displayLink;
    (void)callback;
    (void)context;
    return -1;
}

int32_t CVDisplayLinkStart(void *displayLink) {
    (void)displayLink;
    return -1;
}

int32_t CVDisplayLinkStop(void *displayLink) {
    (void)displayLink;
    return -1;
}

uint32_t CVDisplayLinkIsRunning(void *displayLink) {
    (void)displayLink;
    return 0;
}

void CVDisplayLinkRelease(void *displayLink) {
    (void)displayLink;
}

// HIShapeGetBounds returns the same rectangle it writes. A generic stub would report success while
// leaving the caller's CGRect untouched.
CGRect *HIShapeGetBounds(void *shape, CGRect *bounds) {
    (void)shape;
    if (!bounds) return NULL;
    *bounds = CGRectZero;
    return bounds;
}

// Both return a paper dimension in points as a double, not a pointer.
double PMPaperGetHeight(void *paper) {
    (void)paper;
    return 0.0;
}

double PMPaperGetWidth(void *paper) {
    (void)paper;
    return 0.0;
}
