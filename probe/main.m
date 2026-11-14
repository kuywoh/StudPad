// StudPad probe: does this sideloader re-sign nested Mach-O images, and can the app dlopen them?
//
// Two images are embedded:
//   Frameworks/ProbeKit.framework/ProbeKit   MH_DYLIB, probe_framework_answer() -> 42
//   Frameworks/StudioGuest.bundle/StudioGuest MH_BUNDLE, probe_bundle_answer() -> 43
//
// If both load, SideStore's signing covers nested images, and the Studio probe can use the
// retyped-MH_BUNDLE path without the on-device JIT helper. If only the framework loads, the guest
// can be shipped as a framework-shaped bundle. If neither loads, the helper path is required.
//
// Everything is mirrored to Documents/probe.log (Files > On My iPad > StudPad Probe), so a failure
// still leaves evidence if the process is killed.

#import <UIKit/UIKit.h>
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <mach-o/loader.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static UITextView *gView;
static NSMutableString *gLog;
static NSString *gLogPath;

static void say(NSString *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    NSString *s = [[NSString alloc] initWithFormat:fmt arguments:ap];
    va_end(ap);
    NSString *line = [s stringByAppendingString:@"\n"];

    fprintf(stderr, "%s", line.UTF8String);
    if (!gLog) gLog = [NSMutableString new];
    [gLog appendString:line];

    NSFileHandle *fh = [NSFileHandle fileHandleForWritingAtPath:gLogPath];
    if (!fh) {
        [[NSFileManager defaultManager] createFileAtPath:gLogPath contents:nil attributes:nil];
        fh = [NSFileHandle fileHandleForWritingAtPath:gLogPath];
    }
    if (fh) {
        @try {
            [fh seekToEndOfFile];
            [fh writeData:[line dataUsingEncoding:NSUTF8StringEncoding]];
        } @catch (NSException *e) {
            fprintf(stderr, "log write failed: %s\n", e.reason.UTF8String);
        }
        [fh closeFile];
    }

    dispatch_async(dispatch_get_main_queue(), ^{
        if (gView) {
            gView.text = gLog;
            if (gLog.length) [gView scrollRangeToVisible:NSMakeRange(gLog.length - 1, 1)];
        }
    });
}

// LC_CODE_SIGNATURE's blob, for the kernel's library-validation calls.
static bool signature_blob(const char *path, uint32_t *offset, uint32_t *size) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return false;
    struct mach_header_64 mh;
    bool found = false;
    if (pread(fd, &mh, sizeof mh, 0) == (ssize_t)sizeof mh && mh.magic == MH_MAGIC_64) {
        char *cmds = malloc(mh.sizeofcmds);
        if (cmds && pread(fd, cmds, mh.sizeofcmds, sizeof mh) == (ssize_t)mh.sizeofcmds) {
            for (uint32_t i = 0, off = 0; i < mh.ncmds && off + sizeof(struct load_command) <= mh.sizeofcmds; i++) {
                struct load_command *lc = (void *)(cmds + off);
                if (lc->cmdsize == 0) break;
                if (lc->cmd == LC_CODE_SIGNATURE) {
                    struct linkedit_data_command *cs = (void *)lc;
                    *offset = cs->dataoff;
                    *size = cs->datasize;
                    found = true;
                    break;
                }
                off += lc->cmdsize;
            }
        }
        free(cmds);
    }
    close(fd);
    return found;
}

static void check_library_validation(const char *path) {
    uint32_t off = 0, size = 0;
    if (!signature_blob(path, &off, &size)) {
        say(@"  lv: no LC_CODE_SIGNATURE");
        return;
    }
    say(@"  lv: LC_CODE_SIGNATURE at %u, %u bytes", off, size);

    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        say(@"  lv: open failed: %s", strerror(errno));
        return;
    }
#ifdef F_ADDFILESIGS_RETURN
    fsignatures_t sigs = {
        .fs_file_start = 0,
        .fs_blob_start = (void *)(uintptr_t)off,
        .fs_blob_size = size,
    };
    int r = fcntl(fd, F_ADDFILESIGS_RETURN, &sigs);
    say(@"  lv: F_ADDFILESIGS_RETURN = %d%s%s", r, r ? ", " : "", r ? strerror(errno) : "");
#else
    say(@"  lv: F_ADDFILESIGS_RETURN is not in this SDK");
#endif

#ifdef F_CHECK_LV
    char msg[1024] = {0};
    fchecklv_t lv = {
        .lv_file_start = 0,
        .lv_error_message_size = sizeof msg,
        .lv_error_message = msg,
    };
    int r = fcntl(fd, F_CHECK_LV, &lv);
    say(@"  lv: F_CHECK_LV = %d%s%s%s%s", r, r ? ", " : "", r ? strerror(errno) : "",
        msg[0] ? ": " : "", msg);
#else
    say(@"  lv: F_CHECK_LV is not in this SDK");
#endif
    close(fd);
}

static void load_one(NSString *relative, const char *symbol, int want) {
    NSString *path = [NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:relative];
    const char *p = path.fileSystemRepresentation;
    struct stat st;
    if (stat(p, &st) != 0) {
        say(@"%@: missing (%s)", relative, strerror(errno));
        return;
    }
    say(@"%@: %lld bytes", relative, (long long)st.st_size);
    check_library_validation(p);

    void *h = dlopen(p, RTLD_NOW | RTLD_LOCAL);
    if (!h) {
        say(@"  dlopen FAILED: %s", dlerror());
        return;
    }
    int (*f)(void) = (int (*)(void))dlsym(h, symbol);
    if (!f) {
        say(@"  dlsym(%s) FAILED: %s", symbol, dlerror());
        dlclose(h);
        return;
    }
    int got = f();
    say(@"  %s() = %d (expected %d) %s", symbol, got, want, got == want ? @"PASS" : @"FAIL");
    dlclose(h);
}

@interface ProbeViewController : UIViewController
@end

@implementation ProbeViewController

- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.blackColor;
    UITextView *tv = [[UITextView alloc] initWithFrame:self.view.bounds];
    tv.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    tv.editable = NO;
    tv.selectable = YES;
    tv.backgroundColor = UIColor.blackColor;
    tv.textColor = UIColor.greenColor;
    tv.font = [UIFont monospacedSystemFontOfSize:12 weight:UIFontWeightRegular];
    [self.view addSubview:tv];
    gView = tv;
    tv.text = gLog ?: @"";
}

- (void)viewDidAppear:(BOOL)animated {
    [super viewDidAppear:animated];
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        [self runProbe];
    });
}

- (void)runProbe {
    say(@"=== StudPad signing probe");
    say(@"device: %@ %@ (%@)", UIDevice.currentDevice.systemName, UIDevice.currentDevice.systemVersion,
        UIDevice.currentDevice.model);
    say(@"bundle: %@", NSBundle.mainBundle.bundlePath);
    say(@"log: %@", gLogPath);

    load_one(@"Frameworks/ProbeKit.framework/ProbeKit", "probe_framework_answer", 42);
    load_one(@"Frameworks/StudioGuest.bundle/StudioGuest", "probe_bundle_answer", 43);

    say(@"=== done");
    say(@"If either image says PASS, nested signing works.");
    say(@"Open Files > On My iPad > StudPad Probe to copy probe.log.");
}

@end

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@end

@implementation AppDelegate
@end

@interface SceneDelegate : UIResponder <UIWindowSceneDelegate>
@property (strong, nonatomic) UIWindow *window;
@end

@implementation SceneDelegate

- (void)scene:(UIScene *)scene
    willConnectToSession:(UISceneSession *)session
                 options:(UISceneConnectionOptions *)connectionOptions {
    UIWindowScene *ws = (UIWindowScene *)scene;
    self.window = [[UIWindow alloc] initWithWindowScene:ws];
    self.window.rootViewController = [ProbeViewController new];
    [self.window makeKeyAndVisible];
}

@end

int main(int argc, char **argv) {
    @autoreleasepool {
        NSString *docs = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
        gLogPath = [docs stringByAppendingPathComponent:@"probe.log"];
        [[NSFileManager defaultManager] createFileAtPath:gLogPath contents:nil attributes:nil];
        return UIApplicationMain(argc, argv, nil, @"AppDelegate");
    }
}
