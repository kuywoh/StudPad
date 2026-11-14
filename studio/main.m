// StudPad Studio probe: can iOS dyld load the official arm64 Studio executable and its Qt frameworks?
//
// The build retypes Studio's MH_EXECUTE to MH_BUNDLE, maps macOS framework paths to iOS paths, and marks
// every missing import weak. This host dlopens it with RTLD_NOW, finds its LC_MAIN, and calls the entry.
// It forces Qt's offscreen platform and Fusion style so the first probe does not depend on Cocoa/AppKit.
//
// stderr and stdout are redirected into Documents/studio.log before anything else, so Qt's own logging
// survives. Every signal writes a backtrace there before the process dies.

#import <UIKit/UIKit.h>
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <errno.h>
#include <execinfo.h>
#include <fcntl.h>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern char **environ;

static UITextView *gView;
static NSMutableString *gLog;
static NSString *gLogPath;
static int gLogFd = -1;
static volatile int gInGuest = 0;

static void say(NSString *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    NSString *s = [[NSString alloc] initWithFormat:fmt arguments:ap];
    va_end(ap);
    NSString *line = [s stringByAppendingString:@"\n"];

    fprintf(stderr, "%s", line.UTF8String);
    fflush(stderr);

    if (!gLog) gLog = [NSMutableString new];
    NSMutableString *snapshot = nil;
    @synchronized (gLog) {
        [gLog appendString:line];
        snapshot = [gLog copy];
    }
    dispatch_async(dispatch_get_main_queue(), ^{
        if (gView) {
            gView.text = snapshot;
            if (snapshot.length) [gView scrollRangeToVisible:NSMakeRange(snapshot.length - 1, 1)];
        }
    });
}

static void crash_signal(int sig) {
    char head[128];
    int n = snprintf(head, sizeof head, "\n=== signal %d (%s) ===\n", sig, strsignal(sig));
    if (gLogFd >= 0) {
        write(gLogFd, head, (size_t)n);
        void *frames[80];
        int count = backtrace(frames, 80);
        backtrace_symbols_fd(frames, count, gLogFd);
        const char tail[] = "=== end ===\n";
        write(gLogFd, tail, sizeof tail - 1);
        fsync(gLogFd);
    }
    _exit(128 + sig);
}

static void uncaught_exception(NSException *e) {
    fprintf(stderr, "\n=== NSException %s: %s ===\n%s\n", e.name.UTF8String,
            e.reason.UTF8String, e.callStackSymbols.description.UTF8String);
    fflush(stderr);
    if (gLogFd >= 0) fsync(gLogFd);
}

static uint64_t guest_entry_offset(const struct mach_header_64 *mh) {
    const uint8_t *p = (const uint8_t *)(mh + 1);
    for (uint32_t i = 0; i < mh->ncmds; i++) {
        const struct load_command *lc = (const void *)p;
        if (lc->cmdsize < sizeof *lc) return 0;
        if (lc->cmd == LC_MAIN) {
            return ((const struct entry_point_command *)lc)->entryoff;
        }
        p += lc->cmdsize;
    }
    return 0;
}

static const struct mach_header_64 *find_guest(uint32_t first) {
    uint32_t count = _dyld_image_count();
    for (uint32_t i = first; i < count; i++) {
        const char *name = _dyld_get_image_name(i);
        if (name && strstr(name, "StudioKit.framework/StudioKit")) {
            return (const struct mach_header_64 *)_dyld_get_image_header(i);
        }
    }
    return NULL;
}

@interface StudioProbeViewController : UIViewController
@end

@implementation StudioProbeViewController

- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.blackColor;
    UITextView *tv = [[UITextView alloc] initWithFrame:self.view.bounds];
    tv.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    tv.editable = NO;
    tv.selectable = YES;
    tv.backgroundColor = UIColor.blackColor;
    tv.textColor = UIColor.greenColor;
    tv.font = [UIFont monospacedSystemFontOfSize:11 weight:UIFontWeightRegular];
    [self.view addSubview:tv];
    gView = tv;
    tv.text = gLog ?: @"";
}

- (void)viewDidAppear:(BOOL)animated {
    [super viewDidAppear:animated];
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1 * NSEC_PER_SEC)),
                       dispatch_get_main_queue(), ^{
            [self runStudio];
        });
    });
}

- (void)runStudio {
    NSString *bundlePath = NSBundle.mainBundle.bundlePath;
    NSString *guest = [bundlePath stringByAppendingPathComponent:@"Frameworks/StudioKit.framework/StudioKit"];
    NSString *plugins = [bundlePath stringByAppendingPathComponent:@"Frameworks/PlugIns"];
    NSString *platforms = [plugins stringByAppendingPathComponent:@"platforms"];

    say(@"=== StudPad Studio load probe ===");
    say(@"device: %@ %@ (%@)", UIDevice.currentDevice.systemName, UIDevice.currentDevice.systemVersion,
        UIDevice.currentDevice.model);
    say(@"bundle: %@", bundlePath);
    say(@"guest: %@", guest);
    say(@"log: %@", gLogPath);
    say(@"Qt: offscreen platform, fusion style");

    setenv("QT_PLUGIN_PATH", plugins.fileSystemRepresentation, 1);
    setenv("QT_QPA_PLATFORM_PLUGIN_PATH", platforms.fileSystemRepresentation, 1);
    setenv("QT_QPA_PLATFORM", "offscreen", 1);
    setenv("QT_STYLE_OVERRIDE", "fusion", 1);
    setenv("QT_LOGGING_RULES", "qt.qpa.*=true", 1);
    setenv("QT_LOGGING_TO_CONSOLE", "1", 1);
    chdir(bundlePath.fileSystemRepresentation);

    uint32_t before = _dyld_image_count();
    say(@"dlopen RTLD_NOW|RTLD_GLOBAL...");
    void *handle = dlopen(guest.fileSystemRepresentation, RTLD_NOW | RTLD_GLOBAL);
    if (!handle) {
        say(@"dlopen FAILED: %s", dlerror());
        return;
    }
    uint32_t after = _dyld_image_count();
    say(@"dlopen returned %p; images %u -> %u", handle, before, after);
    for (uint32_t i = before; i < after; i++) {
        say(@"  image %u: %s", i, _dyld_get_image_name(i));
    }

    const struct mach_header_64 *mh = find_guest(before);
    if (!mh) {
        say(@"guest image not listed by dyld");
        return;
    }
    uint64_t entryoff = guest_entry_offset(mh);
    if (!entryoff) {
        say(@"guest has no LC_MAIN");
        return;
    }
    say(@"guest header %p, entry offset 0x%llx", mh, (unsigned long long)entryoff);

    int (*entry)(int, char **, char **, char **) = (void *)((uintptr_t)mh + entryoff);
    char *argv[] = {(char *)guest.fileSystemRepresentation, NULL};
    say(@"calling Studio entry...");
    gInGuest = 1;
    int rc = entry(1, argv, environ, NULL);
    gInGuest = 0;
    say(@"Studio entry returned %d", rc);
}

@end

@interface ProbeAppDelegate : UIResponder <UIApplicationDelegate>
@end

@implementation ProbeAppDelegate
@end

@interface ProbeSceneDelegate : UIResponder <UIWindowSceneDelegate>
@property (strong, nonatomic) UIWindow *window;
@end

@implementation ProbeSceneDelegate

- (void)scene:(UIScene *)scene
    willConnectToSession:(UISceneSession *)session
                 options:(UISceneConnectionOptions *)connectionOptions {
    UIWindowScene *ws = (UIWindowScene *)scene;
    self.window = [[UIWindow alloc] initWithWindowScene:ws];
    self.window.rootViewController = [StudioProbeViewController new];
    [self.window makeKeyAndVisible];
}

@end

int main(int argc, char **argv) {
    @autoreleasepool {
        NSString *docs = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
        gLogPath = [docs stringByAppendingPathComponent:@"studio.log"];
        gLogFd = open(gLogPath.fileSystemRepresentation, O_WRONLY | O_CREAT | O_APPEND, 0644);
        if (gLogFd >= 0) {
            dup2(gLogFd, STDOUT_FILENO);
            dup2(gLogFd, STDERR_FILENO);
            setvbuf(stdout, NULL, _IONBF, 0);
            setvbuf(stderr, NULL, _IONBF, 0);
        }

        NSSetUncaughtExceptionHandler(uncaught_exception);
        for (int sig = 1; sig < NSIG; sig++) {
            if (sig == SIGKILL || sig == SIGSTOP || sig == SIGCONT) continue;
            signal(sig, crash_signal);
        }

        say(@"=== StudPad Studio probe host ===");
        say(@"log: %@", gLogPath);
        say(@"pid %d", getpid());
        return UIApplicationMain(argc, argv, nil, @"ProbeAppDelegate");
    }
}
