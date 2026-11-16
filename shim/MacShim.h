// Shared between the shim, the generated stubs and the host app. C-safe: the ObjC part is only
// visible to .m files, so tools/plan_shim.py can generate a plain C file that includes this.

#ifndef STUDPAD_MACSHIM_H
#define STUDPAD_MACSHIM_H

#ifdef __OBJC__
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>
#endif

typedef void (*studpad_log_hook)(const char *line);

#ifdef __cplusplus
extern "C" {
#endif

void studpad_set_log_hook(studpad_log_hook hook);
void studpad_log(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
const char *studpad_log_path_c(void);

// Stubs: every symbol Studio needs that iOS does not export lands here (tools/plan_shim.py).
void *studpad_stub(const char *name);
void *studpad_stub_asm(void);
long studpad_stub_count(void);

// Load the retargeted Studio executable and call its LC_MAIN. Blocks until Studio returns.
void studpad_guest_start(void);

// Host glue: the UIViewController passes its container and spinner in.
void studpad_host_ready(void *host_view, void *spinner);
void studpad_set_studio_launch_path(const char *path);
int studpad_debugger_attached(void);
int studpad_increased_memory_enabled(void);
void studpad_present_view(void *view);
void studpad_set_log_overlay(void *view);
void studpad_set_log_button(void *view);

#ifdef __cplusplus
}
#endif

#ifdef __OBJC__
// Root class for the AppKit/Carbon classes iOS does not have. Generated subclasses (stubs_objc.m)
// answer unknown selectors by logging and returning 0 instead of raising.
@interface MSStubObject : NSObject
@end
#endif

#endif

