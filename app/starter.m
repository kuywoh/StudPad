// StudPad host: a small UIKit setup screen downloads the matching official Roblox Studio
// package's Resources on first run, then launches the retargeted, signed engine in the IPA.
//
// The package download is pinned to the version used by CI, so assets cannot drift away from the
// embedded iOS-compatible StudioKit. Logs remain in Documents/studio.log.

#import <UIKit/UIKit.h>
#import <Foundation/Foundation.h>
#import <CommonCrypto/CommonDigest.h>
#include <execinfo.h>
#include <fcntl.h>
#include <signal.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <stdio.h>
#import "MacShim.h"
#import "zip_resources.h"

static UITextView *gLogView;
static UIButton *gLogButton;
static NSMutableString *gText;
static UIView *gStudioHost;
static UIView *gSetupView;
static UIActivityIndicatorView *gSpinner;
static UILabel *gStatusLabel;
static UILabel *gMemoryStatusLabel;
static UILabel *gJitStatusLabel;
static UILabel *gProgressLabel;
static UIProgressView *gProgressView;
static UIButton *gDownloadButton;
static UIButton *gLaunchButton;

static void host_log(const char *line) {
    if (!gText) gText = [NSMutableString new];
    NSString *text = [NSString stringWithUTF8String:line];
    if (!text) return;
    @synchronized(gText) { [gText appendString:text]; }
    NSMutableString *snapshot = nil;
    @synchronized(gText) { snapshot = [gText copy]; }
    dispatch_async(dispatch_get_main_queue(), ^{
        gLogView.text = snapshot;
        if (snapshot.length) [gLogView scrollRangeToVisible:NSMakeRange(snapshot.length - 1, 1)];
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

@interface StudPadViewController : UIViewController <NSURLSessionDownloadDelegate>
@property(nonatomic, strong) NSURLSession *downloadSession;
@property(nonatomic, strong) NSURL *downloadedZipURL;
@property(nonatomic, strong) NSURL *packageURL;
@property(nonatomic, strong) NSDictionary *packageManifest;
@property(nonatomic, copy) NSString *studioVersion;
@property(nonatomic, copy) NSString *downloadFailure;
@end

@implementation StudPadViewController

- (NSURL *)supportRoot {
    NSURL *base = [[NSFileManager defaultManager]
        URLsForDirectory:NSApplicationSupportDirectory inDomains:NSUserDomainMask].firstObject;
    NSURL *root = [base URLByAppendingPathComponent:@"StudPad" isDirectory:YES];
    [[NSFileManager defaultManager] createDirectoryAtURL:root
                             withIntermediateDirectories:YES attributes:nil error:nil];
    return root;
}

- (NSURL *)resourcesURL {
    return [[[[self supportRoot] URLByAppendingPathComponent:@"RobloxStudio.app" isDirectory:YES]
        URLByAppendingPathComponent:@"Contents" isDirectory:YES]
        URLByAppendingPathComponent:@"Resources" isDirectory:YES];
}

- (BOOL)studioContentIsReady {
    NSURL *root = [self supportRoot];
    NSString *stored = [NSString stringWithContentsOfURL:[root URLByAppendingPathComponent:@"studio-content.version"]
                                                encoding:NSUTF8StringEncoding error:nil];
    stored = [stored stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    NSString *settings = [[self resourcesURL] URLByAppendingPathComponent:@"AppSettings.xml"].path;
    return [stored isEqualToString:self.studioVersion] &&
           [[NSFileManager defaultManager] fileExistsAtPath:settings];
}

- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = [UIColor colorWithRed:0.055 green:0.07 blue:0.1 alpha:1];

    NSString *manifestPath = [[NSBundle mainBundle] pathForResource:@"StudioPackage" ofType:@"plist"];
    self.packageManifest = manifestPath ? [NSDictionary dictionaryWithContentsOfFile:manifestPath] : nil;
    NSString *urlText = self.packageManifest[@"package_url"];
    NSURL *url = [NSURL URLWithString:urlText ?: @""];
    if ([url.scheme isEqualToString:@"https"] &&
        [url.host isEqualToString:@"setup.rbxcdn.com"] &&
        [url.path hasPrefix:@"/mac/arm64/version-"] &&
        [url.path hasSuffix:@"-RobloxStudioApp.zip"] &&
        [self.packageManifest[@"package_sha256"] length] == CC_SHA256_DIGEST_LENGTH * 2 &&
        [self.packageManifest[@"app_bundle_name"] hasSuffix:@".app"]) {
        self.packageURL = url;
        self.studioVersion = self.packageManifest[@"studio_version"];
    } else {
        self.packageManifest = nil;
        self.studioVersion = nil;
    }

    gStudioHost = [[UIView alloc] initWithFrame:self.view.bounds];
    gStudioHost.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    gStudioHost.backgroundColor = UIColor.blackColor;
    gStudioHost.hidden = YES;
    [self.view addSubview:gStudioHost];

    gSpinner = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleLarge];
    gSpinner.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:gSpinner];
    [NSLayoutConstraint activateConstraints:@[
        [gSpinner.centerXAnchor constraintEqualToAnchor:self.view.centerXAnchor],
        [gSpinner.centerYAnchor constraintEqualToAnchor:self.view.centerYAnchor],
    ]];

    gLogView = [[UITextView alloc] initWithFrame:CGRectZero];
    gLogView.translatesAutoresizingMaskIntoConstraints = NO;
    gLogView.editable = NO;
    gLogView.selectable = YES;
    gLogView.textColor = UIColor.greenColor;
    gLogView.backgroundColor = [UIColor colorWithWhite:0 alpha:0.88];
    gLogView.font = [UIFont monospacedSystemFontOfSize:9 weight:UIFontWeightRegular];
    gLogView.text = @"StudPad log";
    gLogView.hidden = YES;
    [self.view addSubview:gLogView];
    studpad_set_log_overlay((__bridge void *)gLogView);

    gLogButton = [UIButton buttonWithType:UIButtonTypeSystem];
    gLogButton.translatesAutoresizingMaskIntoConstraints = NO;
    gLogButton.backgroundColor = [UIColor colorWithWhite:0 alpha:0.72];
    gLogButton.layer.cornerRadius = 8;
    [gLogButton setTitle:@"Logs" forState:UIControlStateNormal];
    [gLogButton setTitleColor:UIColor.whiteColor forState:UIControlStateNormal];
    [gLogButton addTarget:self action:@selector(toggleLogPanel:)
         forControlEvents:UIControlEventTouchUpInside];
    gLogButton.hidden = YES;
    [self.view addSubview:gLogButton];
    studpad_set_log_button((__bridge void *)gLogButton);
    [NSLayoutConstraint activateConstraints:@[
        [gLogButton.trailingAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.trailingAnchor constant:-12],
        [gLogButton.topAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.topAnchor constant:12],
        [gLogButton.widthAnchor constraintGreaterThanOrEqualToConstant:54],
        [gLogButton.heightAnchor constraintEqualToConstant:36],
        [gLogView.leadingAnchor constraintEqualToAnchor:self.view.leadingAnchor],
        [gLogView.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor],
        [gLogView.bottomAnchor constraintEqualToAnchor:self.view.bottomAnchor],
        [gLogView.heightAnchor constraintEqualToAnchor:self.view.heightAnchor multiplier:0.45],
    ]];

    UIScrollView *scroll = [UIScrollView new];
    scroll.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:scroll];
    [NSLayoutConstraint activateConstraints:@[
        [scroll.leadingAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.leadingAnchor],
        [scroll.trailingAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.trailingAnchor],
        [scroll.topAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.topAnchor],
        [scroll.bottomAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.bottomAnchor],
    ]];

    gSetupView = scroll;

    UIStackView *stack = [[UIStackView alloc] init];
    stack.axis = UILayoutConstraintAxisVertical;
    stack.spacing = 14;
    stack.alignment = UIStackViewAlignmentFill;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [scroll addSubview:stack];
    NSLayoutConstraint *stackWidth = [stack.widthAnchor constraintEqualToAnchor:scroll.frameLayoutGuide.widthAnchor
                                                                      constant:-44];
    stackWidth.priority = UILayoutPriorityDefaultHigh;
    [NSLayoutConstraint activateConstraints:@[
        [stack.centerXAnchor constraintEqualToAnchor:scroll.frameLayoutGuide.centerXAnchor],
        [stack.topAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.topAnchor constant:28],
        [stack.bottomAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.bottomAnchor constant:-28],
        stackWidth,
        [stack.widthAnchor constraintLessThanOrEqualToConstant:640],
    ]];

    UILabel *title = [UILabel new];
    title.text = @"Roblox Studio on iPad";
    title.textColor = UIColor.whiteColor;
    title.font = [UIFont systemFontOfSize:30 weight:UIFontWeightBold];
    title.numberOfLines = 0;
    [stack addArrangedSubview:title];

    UILabel *subtitle = [UILabel new];
    subtitle.textColor = [UIColor colorWithWhite:0.82 alpha:1];
    subtitle.font = [UIFont systemFontOfSize:16];
    subtitle.numberOfLines = 0;
    [stack addArrangedSubview:subtitle];
    if (self.studioVersion) {
        subtitle.text = [NSString stringWithFormat:
            @"Download the official Roblox Studio Mac package for version %@. StudPad keeps the iOS-compatible engine here and fetches the matching Studio resources from Roblox's CDN.",
            self.studioVersion];
    } else {
        subtitle.text = @"This build is missing its pinned Roblox Studio download manifest. Install a fresh build from the latest workflow run.";
    }

    gStatusLabel = [UILabel new];
    gStatusLabel.textColor = [UIColor colorWithWhite:0.92 alpha:1];
    gStatusLabel.font = [UIFont systemFontOfSize:15 weight:UIFontWeightMedium];
    gStatusLabel.numberOfLines = 0;
    [stack addArrangedSubview:gStatusLabel];

    gProgressView = [[UIProgressView alloc] initWithProgressViewStyle:UIProgressViewStyleDefault];
    gProgressView.progressTintColor = [UIColor colorWithRed:0.2 green:0.72 blue:0.52 alpha:1];
    gProgressView.hidden = YES;
    [stack addArrangedSubview:gProgressView];

    gProgressLabel = [UILabel new];
    gProgressLabel.textColor = [UIColor colorWithWhite:0.72 alpha:1];
    gProgressLabel.font = [UIFont systemFontOfSize:13];
    gProgressLabel.numberOfLines = 0;
    gProgressLabel.hidden = YES;
    [stack addArrangedSubview:gProgressLabel];

    gDownloadButton = [self buttonWithTitle:@"Download Studio from Roblox" selector:@selector(downloadStudio:) primary:YES];
    [stack addArrangedSubview:gDownloadButton];
    gLaunchButton = [self buttonWithTitle:@"Open Roblox Studio" selector:@selector(launchStudio:) primary:YES];
    [stack addArrangedSubview:gLaunchButton];

    UILabel *setupHeading = [UILabel new];
    setupHeading.text = @"Optional setup";
    setupHeading.textColor = UIColor.whiteColor;
    setupHeading.font = [UIFont systemFontOfSize:19 weight:UIFontWeightSemibold];
    [stack addArrangedSubview:setupHeading];

    gMemoryStatusLabel = [UILabel new];
    gMemoryStatusLabel.textColor = [UIColor colorWithWhite:0.82 alpha:1];
    gMemoryStatusLabel.font = [UIFont systemFontOfSize:14];
    gMemoryStatusLabel.numberOfLines = 0;
    [stack addArrangedSubview:gMemoryStatusLabel];
    [stack addArrangedSubview:[self buttonWithTitle:@"Set up GetMoreRam" selector:@selector(showGetMoreRam:) primary:NO]];

    gJitStatusLabel = [UILabel new];
    gJitStatusLabel.textColor = [UIColor colorWithWhite:0.82 alpha:1];
    gJitStatusLabel.font = [UIFont systemFontOfSize:14];
    gJitStatusLabel.numberOfLines = 0;
    [stack addArrangedSubview:gJitStatusLabel];
    [stack addArrangedSubview:[self buttonWithTitle:@"Enable JIT with StikDebug" selector:@selector(showStikDebug:) primary:NO]];

    UILabel *note = [UILabel new];
    note.text = @"JIT is optional for the current Studio build. The button hands this running app to StikDebug; it does not install StikDebug or change the app's signing profile.";
    note.textColor = [UIColor colorWithWhite:0.65 alpha:1];
    note.font = [UIFont systemFontOfSize:13];
    note.numberOfLines = 0;
    [stack addArrangedSubview:note];

    studpad_set_log_hook(host_log);
    [self refreshSetupStatus];
}

- (UIButton *)buttonWithTitle:(NSString *)title selector:(SEL)selector primary:(BOOL)primary {
    UIButton *button = [UIButton buttonWithType:UIButtonTypeSystem];
    button.translatesAutoresizingMaskIntoConstraints = NO;
    button.backgroundColor = primary
        ? [UIColor colorWithRed:0.12 green:0.62 blue:0.43 alpha:1]
        : [UIColor colorWithWhite:0.18 alpha:1];
    button.layer.cornerRadius = 10;
    [button setTitle:title forState:UIControlStateNormal];
    [button setTitleColor:UIColor.whiteColor forState:UIControlStateNormal];
    button.titleLabel.font = [UIFont systemFontOfSize:16 weight:UIFontWeightSemibold];
    [button.heightAnchor constraintGreaterThanOrEqualToConstant:48].active = YES;
    [button addTarget:self action:selector forControlEvents:UIControlEventTouchUpInside];
    return button;
}

- (void)refreshSetupStatus {
    BOOL ready = self.studioVersion && [self studioContentIsReady];
    if (!self.packageManifest) {
        gStatusLabel.text = @"Download information is missing. Install a new StudPad build.";
        gDownloadButton.hidden = YES;
        gLaunchButton.hidden = YES;
    } else if (ready) {
        unsigned long long bytes = [self.packageManifest[@"resource_bytes"] unsignedLongLongValue];
        gStatusLabel.text = [NSString stringWithFormat:@"Studio %@ is ready. %@ of assets are stored on this iPad.",
            self.studioVersion, [NSByteCountFormatter stringFromByteCount:(long long)bytes countStyle:NSByteCountFormatterCountStyleFile]];
        gDownloadButton.hidden = YES;
        gLaunchButton.hidden = NO;
    } else {
        unsigned long long bytes = [self.packageManifest[@"package_bytes"] unsignedLongLongValue];
        gStatusLabel.text = [NSString stringWithFormat:@"The first download is %@. Keep StudPad open while it downloads and installs the Studio resources.",
            [NSByteCountFormatter stringFromByteCount:(long long)bytes countStyle:NSByteCountFormatterCountStyleFile]];
        gDownloadButton.hidden = NO;
        gLaunchButton.hidden = YES;
    }

    gMemoryStatusLabel.text = studpad_increased_memory_enabled()
        ? @"GetMoreRam: increased memory limit is active in this installed signing profile."
        : @"GetMoreRam: not active in this install. Add the capability in GetMoreRam, then refresh or reinstall StudPad in SideStore.";
    gJitStatusLabel.text = studpad_debugger_attached() == 1
        ? @"StikDebug: a debugger is attached to StudPad."
        : @"StikDebug: no debugger is attached. Set it up only if Studio reports an executable-memory problem.";
}

- (void)downloadStudio:(UIButton *)sender {
    (void)sender;
    if (!self.packageURL || !self.packageManifest) return;
    gDownloadButton.enabled = NO;
    gProgressView.hidden = NO;
    gProgressLabel.hidden = NO;
    gProgressLabel.text = @"Connecting to Roblox…";
    gProgressView.progress = 0;
    gStatusLabel.text = @"Downloading the version-pinned Roblox Studio package…";
    self.downloadedZipURL = nil;
    self.downloadFailure = nil;
    NSURLSessionConfiguration *configuration = [NSURLSessionConfiguration defaultSessionConfiguration];
    configuration.timeoutIntervalForRequest = 60;
    configuration.timeoutIntervalForResource = 60 * 60;
    self.downloadSession = [NSURLSession sessionWithConfiguration:configuration delegate:self delegateQueue:nil];
    NSURLSessionDownloadTask *task = [self.downloadSession downloadTaskWithURL:self.packageURL];
    [task resume];
}

- (void)URLSession:(NSURLSession *)session downloadTask:(NSURLSessionDownloadTask *)downloadTask
 didWriteData:(int64_t)bytesWritten totalBytesWritten:(int64_t)totalBytesWritten
 totalBytesExpectedToWrite:(int64_t)totalBytesExpectedToWrite {
    (void)session;
    dispatch_async(dispatch_get_main_queue(), ^{
        int64_t total = totalBytesExpectedToWrite > 0
            ? totalBytesExpectedToWrite : [self.packageManifest[@"package_bytes"] longLongValue];
        gProgressView.progress = total > 0 ? (float)totalBytesWritten / (float)total : 0;
        gProgressLabel.text = [NSString stringWithFormat:@"%@ of %@",
            [NSByteCountFormatter stringFromByteCount:totalBytesWritten countStyle:NSByteCountFormatterCountStyleFile],
            [NSByteCountFormatter stringFromByteCount:total countStyle:NSByteCountFormatterCountStyleFile]];
    });
    (void)bytesWritten;
    (void)downloadTask;
}

- (void)URLSession:(NSURLSession *)session downloadTask:(NSURLSessionDownloadTask *)downloadTask
 didFinishDownloadingToURL:(NSURL *)location {
    (void)session;
    NSHTTPURLResponse *response = (NSHTTPURLResponse *)downloadTask.response;
    if (response.statusCode < 200 || response.statusCode >= 300) {
        self.downloadFailure = [NSString stringWithFormat:@"Roblox CDN returned HTTP %ld.", (long)response.statusCode];
        return;
    }
    NSURL *destination = [[self supportRoot] URLByAppendingPathComponent:@"studio-package.zip"];
    [[NSFileManager defaultManager] removeItemAtURL:destination error:nil];
    NSError *error = nil;
    if (![[NSFileManager defaultManager] moveItemAtURL:location toURL:destination error:&error]) {
        self.downloadFailure = error.localizedDescription ?: @"Could not save the download.";
        return;
    }
    self.downloadedZipURL = destination;
}

- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
 didCompleteWithError:(NSError *)error {
    (void)session;
    (void)task;
    NSURL *archive = self.downloadedZipURL;
    NSString *failure = self.downloadFailure;
    self.downloadedZipURL = nil;
    self.downloadFailure = nil;
    if (error || failure || !archive) {
        NSString *message = failure ?: error.localizedDescription ?: @"The download did not finish.";
        dispatch_async(dispatch_get_main_queue(), ^{
            self.downloadSession = nil;
            gDownloadButton.enabled = YES;
            gStatusLabel.text = [@"Download failed: " stringByAppendingString:message];
            gProgressView.hidden = YES;
            gProgressLabel.hidden = YES;
        });
        return;
    }

    dispatch_async(dispatch_get_main_queue(), ^{
        gProgressView.progress = 1;
        gProgressLabel.text = @"Checking the package checksum and installing Studio resources…";
        gStatusLabel.text = @"Installing Studio resources. This can take a few minutes.";
        gDownloadButton.enabled = NO;
    });
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        NSError *installError = nil;
        unsigned long long expectedBytes = [self.packageManifest[@"package_bytes"] unsignedLongLongValue];
        NSDictionary *attributes = [[NSFileManager defaultManager] attributesOfItemAtPath:archive.path error:&installError];
        unsigned long long actualBytes = [attributes[NSFileSize] unsignedLongLongValue];
        NSString *expectedHash = [self.packageManifest[@"package_sha256"] lowercaseString];
        NSString *actualHash = [self sha256ForFile:archive error:&installError];
        if (!installError && (actualBytes != expectedBytes || ![actualHash isEqualToString:expectedHash])) {
            installError = [NSError errorWithDomain:@"StudPadDownload" code:1
                userInfo:@{NSLocalizedDescriptionKey:@"The downloaded Studio package did not match the build's pinned size and SHA-256."}];
        }

        NSURL *root = [self supportRoot];
        NSURL *staging = [root URLByAppendingPathComponent:@"studio-content.partial" isDirectory:YES];
        [[NSFileManager defaultManager] removeItemAtURL:staging error:nil];
        [[NSFileManager defaultManager] createDirectoryAtURL:staging
                                withIntermediateDirectories:YES attributes:nil error:&installError];
        char zipError[512] = {0};
        if (!installError && studpad_extract_resources_zip(
                archive.fileSystemRepresentation, staging.fileSystemRepresentation,
                [self.packageManifest[@"app_bundle_name"] UTF8String], zipError, sizeof(zipError)) != 0) {
            installError = [NSError errorWithDomain:@"StudPadDownload" code:2
                userInfo:@{NSLocalizedDescriptionKey:[NSString stringWithUTF8String:zipError] ?: @"Could not extract Studio resources."}];
        }

        if (!installError) {
            NSURL *resources = [self resourcesURL];
            NSURL *parent = resources.URLByDeletingLastPathComponent;
            [[NSFileManager defaultManager] createDirectoryAtURL:parent
                                    withIntermediateDirectories:YES attributes:nil error:&installError];
            if (!installError) {
                [[NSFileManager defaultManager] removeItemAtURL:resources error:nil];
                if (![[NSFileManager defaultManager] moveItemAtURL:staging toURL:resources error:&installError]) {
                    installError = installError ?: [NSError errorWithDomain:@"StudPadDownload" code:3
                        userInfo:@{NSLocalizedDescriptionKey:@"Could not install Studio resources."}];
                }
            }
        }
        if (!installError) {
            NSString *versionPath = [[root URLByAppendingPathComponent:@"studio-content.version"] path];
            NSError *writeError = nil;
            [self.studioVersion writeToFile:versionPath atomically:YES encoding:NSUTF8StringEncoding error:&writeError];
            installError = writeError;
        }

        [[NSFileManager defaultManager] removeItemAtURL:archive error:nil];
        if (installError) [[NSFileManager defaultManager] removeItemAtURL:staging error:nil];

        dispatch_async(dispatch_get_main_queue(), ^{
            self.downloadSession = nil;
            gDownloadButton.enabled = YES;
            gProgressView.hidden = YES;
            gProgressLabel.hidden = YES;
            if (installError) {
                gStatusLabel.text = [@"Studio setup failed: " stringByAppendingString:installError.localizedDescription];
                UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"Studio setup failed"
                    message:installError.localizedDescription preferredStyle:UIAlertControllerStyleAlert];
                [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];
                [self presentViewController:alert animated:YES completion:nil];
            } else {
                gStatusLabel.text = @"Studio resources are ready.";
                [self refreshSetupStatus];
            }
        });
    });
}

- (NSString *)sha256ForFile:(NSURL *)url error:(NSError **)error {
    FILE *input = fopen(url.fileSystemRepresentation, "rb");
    if (!input) {
        if (error) *error = [NSError errorWithDomain:NSPOSIXErrorDomain code:errno
            userInfo:@{NSLocalizedDescriptionKey:@"Could not read the downloaded Studio package."}];
        return nil;
    }
    CC_SHA256_CTX context;
    CC_SHA256_Init(&context);
    unsigned char buffer[1024 * 1024];
    size_t count;
    while ((count = fread(buffer, 1, sizeof(buffer), input)) > 0)
        CC_SHA256_Update(&context, buffer, (CC_LONG)count);
    BOOL readFailed = ferror(input);
    fclose(input);
    if (readFailed) {
        if (error) *error = [NSError errorWithDomain:@"StudPadDownload" code:4
            userInfo:@{NSLocalizedDescriptionKey:@"Could not read the complete Studio package."}];
        return nil;
    }
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256_Final(digest, &context);
    NSMutableString *hex = [NSMutableString stringWithCapacity:CC_SHA256_DIGEST_LENGTH * 2];
    for (NSUInteger i = 0; i < sizeof(digest); i++) [hex appendFormat:@"%02x", digest[i]];
    return hex;
}

- (void)launchStudio:(UIButton *)sender {
    (void)sender;
    if (![self studioContentIsReady]) {
        [self refreshSetupStatus];
        return;
    }

    NSString *bundle = NSBundle.mainBundle.bundlePath;
    NSString *guest = [bundle stringByAppendingPathComponent:@"Frameworks/StudioKit"];
    NSURL *launchDirectory = [[[self resourcesURL] URLByDeletingLastPathComponent]
        URLByAppendingPathComponent:@"MacOS" isDirectory:YES];
    [[NSFileManager defaultManager] createDirectoryAtURL:launchDirectory
                            withIntermediateDirectories:YES attributes:nil error:nil];
    NSString *launchPath = [launchDirectory URLByAppendingPathComponent:@"RobloxStudio"].path;
    unlink(launchPath.fileSystemRepresentation);
    if (symlink(guest.fileSystemRepresentation, launchPath.fileSystemRepresentation) != 0) {
        UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"Could not prepare Studio"
            message:[NSString stringWithFormat:@"Could not prepare the Studio launch path: %s", strerror(errno)]
            preferredStyle:UIAlertControllerStyleAlert];
        [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];
        [self presentViewController:alert animated:YES completion:nil];
        return;
    }
    studpad_set_studio_launch_path(launchPath.fileSystemRepresentation);

    gSetupView.hidden = YES;
    gStudioHost.hidden = NO;
    gLogView.hidden = NO;
    [gSpinner startAnimating];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)),
                   dispatch_get_main_queue(), ^{
        studpad_guest_start();
    });
}

- (void)showGetMoreRam:(UIButton *)sender {
    (void)sender;
    NSString *message = @"GetMoreRam adds the memory capability to the Apple ID's app profile. Use the same Apple ID as SideStore, refresh App IDs, select com.kuywoh.studpadstudio, add Increased Memory Limit, then refresh or reinstall StudPad in SideStore. The change cannot be applied from inside StudPad.";
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"Set up GetMoreRam"
        message:message preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:@"Open GetMoreRam" style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) {
        [self openURL:[NSURL URLWithString:@"https://github.com/hugeBlack/GetMoreRam"] failureMessage:@"GetMoreRam could not be opened."];
    }]];
    [alert addAction:[UIAlertAction actionWithTitle:@"Done" style:UIAlertActionStyleCancel handler:nil]];
    [self presentViewController:alert animated:YES completion:nil];
}

- (void)showStikDebug:(UIButton *)sender {
    (void)sender;
    NSString *message = @"Install and pair StikDebug first. On iOS 26+, set up its pairing and LocalDevVPN, then assign StikDebug's universal.js script to StudPad. Tap Continue to ask StikDebug to enable JIT for this running process. JIT is optional for the current Studio build.";
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"Enable JIT with StikDebug"
        message:message preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:@"Continue to StikDebug" style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) {
        NSURLComponents *components = [NSURLComponents componentsWithString:@"stikjit://enable-jit"];
        components.queryItems = @[
            [NSURLQueryItem queryItemWithName:@"bundle-id" value:NSBundle.mainBundle.bundleIdentifier ?: @"com.kuywoh.studpadstudio"],
            [NSURLQueryItem queryItemWithName:@"pid" value:[NSString stringWithFormat:@"%d", getpid()]],
        ];
        [self openURL:components.URL failureMessage:@"StikDebug did not open. Install and pair it, then try again."];
    }]];
    [alert addAction:[UIAlertAction actionWithTitle:@"StikDebug setup guide" style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) {
        [self openURL:[NSURL URLWithString:@"https://github.com/StikDebug/StikDebug"] failureMessage:@"Could not open the StikDebug guide."];
    }]];
    [alert addAction:[UIAlertAction actionWithTitle:@"Cancel" style:UIAlertActionStyleCancel handler:nil]];
    [self presentViewController:alert animated:YES completion:nil];
}

- (void)openURL:(NSURL *)url failureMessage:(NSString *)message {
    if (!url) return;
    [[UIApplication sharedApplication] openURL:url options:@{} completionHandler:^(BOOL success) {
        if (!success) {
            dispatch_async(dispatch_get_main_queue(), ^{
                UIAlertController *alert = [UIAlertController alertControllerWithTitle:@"Could not open"
                    message:message preferredStyle:UIAlertControllerStyleAlert];
                [alert addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];
                [self presentViewController:alert animated:YES completion:nil];
            });
        }
    }];
}

- (void)toggleLogPanel:(UIButton *)sender {
    gLogView.hidden = !gLogView.hidden;
    [sender setTitle:gLogView.hidden ? @"Logs" : @"Hide log" forState:UIControlStateNormal];
}

- (void)viewDidAppear:(BOOL)animated {
    [super viewDidAppear:animated];
    studpad_host_ready((__bridge void *)gStudioHost, (__bridge void *)gSpinner);
    if (!gSetupView) return;
    [self refreshSetupStatus];
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
    NSString *text = [NSString stringWithFormat:@"NSException %@: %@\n%@",
                      exception.name, exception.reason, exception.callStackSymbols.description];
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
