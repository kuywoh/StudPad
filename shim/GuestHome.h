#ifndef STUDPAD_GUEST_HOME_H
#define STUDPAD_GUEST_HOME_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    STUDPAD_GUEST_HOME_OK = 0,
    STUDPAD_GUEST_HOME_INVALID,
    STUDPAD_GUEST_HOME_PATH_TOO_LONG,
    STUDPAD_GUEST_HOME_MKDIR_FAILED,
    STUDPAD_GUEST_HOME_NOT_DIRECTORY,
    STUDPAD_GUEST_HOME_PROBE_FAILED,
} studpad_guest_home_status;

// Create base/component (component may contain slash-separated subdirectories), then prove it is
// writable with a unique O_CREAT|O_EXCL probe. On success, copies the directory into out and
// returns OK. On failure, leaves out empty and stores the failing errno in errOut when it is not
// NULL. The probe never reuses a fixed name, so a stale file from a previous launch cannot make a
// writable home look broken.
studpad_guest_home_status studpad_prepare_guest_home(const char *base, const char *component,
                                                     char *out, size_t outSize, int *errOut);

const char *studpad_guest_home_status_name(studpad_guest_home_status status);

#ifdef __cplusplus
}
#endif

#endif
