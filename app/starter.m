// StudPad host: a normal UIKit app (so the 20 s launch watchdog is satisfied) that shows the log and
// then hands the main thread to the shim, which loads the retargeted Studio executable.
//
// The log is on screen and in Documents/studio.log (visible in Files → On My iPad → StudPad Studio).
// Everything is written before Studio starts, so a crash still leaves the log behind.

#import <UIKit/UIKit.h>
#import <Foundation/Foundation.h>
#include <execinfo.h>
#include <fcntl.h>
#include <signal.h>
#include <string.h>
#include <unistd.h>
#import "MacShim.h"

static UITextView *gLogView;
static NSMutableString *gText;
static UIView *gStudioHost;
static UIActivityIndicatorView *gSpinner;

static void host_log(const char *line) {
    if (!gText) gText = [NSMutableString new];
    NSString *text = [NSString stringWithUTF8String:line];
    if (!text) return;
    // Studio runs on the main thread, so the run loop is the only way the view gets updated.
    @synchronized(gText) {
        [gText appendString:text];
    }
    NSMutableString *snapshot = nil;
    @synchronized(gText) {
        snapshot = [gText copy];
    }
    dispatch_async(dispatch_get_main_queue(), ^{
        gLogView.text = snapshot;
        if (snapshot.length) {
            [gLogView scrollRangeToVisible:NSMakeRange(snapshot.length - 1, 1)];
        }
    });
}

static void crash_signal(int sig) {
    const char *name = strsignal(sig);
    char head[160];
    snprintf(head, sizeof head, "\n=== signal %d (%s) ===\n", sig, name ? name : "?");
    int fd = open(studpad_log_path_c(), O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd >= 0) {
        ssize_t ignored = write(fd, head, strlen(head));
        void *frames[80];
        int count = backtrace(frames, 80);
        backtrace_symbols_fd(frames, count, fd);
        const char tail[] = "=== end ===\n";
        ignored = write(fd, tail, sizeof tail - 1);
        (void)ignored;
        fsync(fd);
        close(fd);
    }
    _exit(128 + sig);
}

@interface StudPadViewController : UIViewController
@end

@implementation StudPadViewController

- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.blackColor;

    gStudioHost = [[UIView alloc] initWithFrame:self.view.bounds];
    gStudioHost.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    gStudioHost.backgroundColor = UIColor.blackColor;
    [self.view addSubview:gStudioHost];

    gSpinner = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleLarge];
    gSpinner.center = CGPointMake(CGRectGetMidX(self.view.bounds), CGRectGetMidY(self.view.bounds) / 2);
    gSpinner.autoresizingMask = UIViewAutoresizingFlexibleLeftMargin | UIViewAutoresizingFlexibleRightMargin;
    [self.view addSubview:gSpinner];

    CGFloat height = self.view.bounds.size.height;
    gLogView = [[UITextView alloc] initWithFrame:CGRectMake(0, height * 0.55, self.view.bounds.size.width, height * 0.45)];
    gLogView.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleTopMargin;
    gLogView.editable = NO;
    gLogView.selectable = YES;
    gLogView.textColor = UIColor.greenColor;
    gLogView.backgroundColor = [UIColor colorWithWhite:0 alpha:0.85];
    gLogView.font = [UIFont monospacedSystemFontOfSize:9 weight:UIFontWeightRegular];
    gLogView.text = @"starting…";
    [self.view addSubview:gLogView];

    studpad_set_log_hook(host_log);
}

- (void)viewDidAppear:(BOOL)animated {
    [super viewDidAppear:animated];
    studpad_host_ready((__bridge void *)gStudioHost, (__bridge void *)gSpinner);
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        // A beat for the first frame, then Studio owns the main thread. It pumps the main run loop
        // from the shim whenever it waits, which is what keeps the view updating.
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.7 * NSEC_PER_SEC)),
                       dispatch_get_main_queue(), ^{
                           studpad_guest_start();
                       });
    });
}

- (BOOL)prefersStatusBarHidden { return YES; }
- (BOOL)prefersHomeIndicatorAutoHidden { return YES; }

@end

@interface StudPadAppDelegate : UIResponder <UIApplicationDelegate>
@end

@implementation StudPadAppDelegate
@end

@interface StudPadSceneDelegate : UIResponder <UIWindowSceneDelegate>
@property(strong, nonatomic) UIWindow *window;
@end

@implementation StudPadSceneDelegate

- (void)scene:(UIScene *)scene
    willConnectToSession:(UISceneSession *)session
                 options:(UISceneConnectionOptions *)connectionOptions {
    (void)session;
    (void)connectionOptions;
    UIWindowScene *windowScene = (UIWindowScene *)scene;
    self.window = [[UIWindow alloc] initWithWindowScene:windowScene];
    self.window.rootViewController = [StudPadViewController new];
    [self.window makeKeyAndVisible];
}

@end

static void uncaught_exception(NSException *exception) {
    NSString *text = [NSString stringWithFormat:@"NSException %@: %@\n%@", exception.name,
                                                exception.reason,
                                                exception.callStackSymbols.description];
    host_log(text.UTF8String);
}

int main(int argc, char **argv) {
    @autoreleasepool {
        NSSetUncaughtExceptionHandler(uncaught_exception);
        for (int sig = 1; sig < NSIG; sig++) {
            if (sig == SIGKILL || sig == SIGSTOP || sig == SIGCONT) continue;
            signal(sig, crash_signal);
        }
        return UIApplicationMain(argc, argv, nil, @"StudPadAppDelegate");
    }
}
