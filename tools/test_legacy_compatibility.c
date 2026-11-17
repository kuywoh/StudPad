#include "LegacyCompatibility.h"

#include <assert.h>

static void expect_string(CFStringRef value, CFStringRef expected) {
    assert(value != NULL);
    assert(CFGetTypeID(value) == CFStringGetTypeID());
    assert(CFEqual(value, expected));
}

int main(void) {
    expect_string(NSAppearanceNameAqua, CFSTR("NSAppearanceNameAqua"));
    expect_string(NSAppearanceNameDarkAqua, CFSTR("NSAppearanceNameDarkAqua"));
    expect_string(NSDeviceCMYKColorSpace, CFSTR("NSDeviceCMYKColorSpace"));
    expect_string(NSDeviceRGBColorSpace, CFSTR("NSDeviceRGBColorSpace"));
    expect_string(NSNamedColorSpace, CFSTR("NSNamedColorSpace"));
    expect_string(NSPatternColorSpace, CFSTR("NSPatternColorSpace"));

    // These are data, read as doubles. A generated function stub would put a code address here.
    assert(NSFontWeightRegular == 0.0);
    assert(NSFontWeightUltraLight < NSFontWeightThin);
    assert(NSFontWeightThin < NSFontWeightLight);
    assert(NSFontWeightLight < NSFontWeightRegular);
    assert(NSFontWeightRegular < NSFontWeightMedium);
    assert(NSFontWeightMedium < NSFontWeightSemibold);
    assert(NSFontWeightSemibold < NSFontWeightBold);
    assert(NSFontWeightBold < NSFontWeightHeavy);
    assert(NSFontWeightHeavy < NSFontWeightBlack);

    assert(NSDeviceSize.width == 0.0);
    assert(NSDeviceSize.height == 0.0);
    assert(kIOMasterPortDefault == MACH_PORT_NULL);
    expect_string(kDADiskDescriptionDeviceModelKey, CFSTR("DADiskDescriptionDeviceModelKey"));
    expect_string(kSecImportExportKeychain, CFSTR("kSecImportExportKeychain"));
    expect_string(kUTTagClassOSType, CFSTR("com.apple.ostype"));

    // Struct returns: a generic void * stub would leave width/height in x1/x2 undefined.
    CGRect bounds = CGDisplayBounds(0);
    assert(CGRectEqualToRect(bounds, CGRectZero));
    CGSize size = CGDisplayScreenSize(0);
    assert(CGSizeEqualToSize(size, CGSizeZero));
    CGPoint point = CGEventGetLocation(NULL);
    assert(CGPointEqualToPoint(point, CGPointZero));

    uint32_t displays[4] = {42, 42, 42, 42};
    uint32_t count = 42;
    assert(CGGetDisplaysWithRect(CGRectZero, 4, displays, &count) == kCGErrorFailure);
    assert(count == 0);
    count = 42;
    assert(CGGetOnlineDisplayList(4, displays, &count) == kCGErrorFailure);
    assert(count == 0);

    void *displayLink = (void *)1;
    assert(CVDisplayLinkCreateWithCGDisplay(0, &displayLink) != 0);
    assert(displayLink == NULL);
    assert(CVDisplayLinkSetOutputCallback(NULL, NULL, NULL) != 0);
    assert(CVDisplayLinkStart(NULL) != 0);
    assert(CVDisplayLinkStop(NULL) != 0);
    assert(CVDisplayLinkIsRunning(NULL) == 0);
    CVDisplayLinkRelease(NULL);

    CGRect shapeBounds = {{1.0, 2.0}, {3.0, 4.0}};
    assert(HIShapeGetBounds(NULL, &shapeBounds) == &shapeBounds);
    assert(CGRectEqualToRect(shapeBounds, CGRectZero));
    assert(HIShapeGetBounds(NULL, NULL) == NULL);
    return 0;
}
