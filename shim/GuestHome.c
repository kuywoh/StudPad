#include "GuestHome.h"

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int ensure_directory(const char *path) {
    char work[PATH_MAX];
    size_t length = strlen(path);
    if (length == 0 || length >= sizeof work) {
        errno = ENAMETOOLONG;
        return -1;
    }
    memcpy(work, path, length + 1);

    // Walk the path one separator at a time. This creates the missing parents (Application Support
    // itself is not guaranteed to exist on a fresh container) and checks every existing component
    // is a directory rather than silently proceeding into a file.
    for (char *at = work + 1; *at; at++) {
        if (*at != '/') continue;
        *at = '\0';
        if (mkdir(work, 0700) != 0) {
            struct stat info;
            if (errno != EEXIST || stat(work, &info) != 0 || !S_ISDIR(info.st_mode)) {
                *at = '/';
                return -1;
            }
        }
        *at = '/';
    }

    if (mkdir(work, 0700) != 0) {
        struct stat info;
        if (errno != EEXIST || stat(work, &info) != 0 || !S_ISDIR(info.st_mode)) {
            return -1;
        }
    }
    return 0;
}

static int probe_writable(const char *directory) {
    char template[PATH_MAX];
    int written = snprintf(template, sizeof template, "%s/.studpad-write-probe.XXXXXX", directory);
    if (written < 0 || (size_t)written >= sizeof template) {
        errno = ENAMETOOLONG;
        return -1;
    }

    int fd = mkstemp(template);
    if (fd < 0) return -1;

    int saved = 0;
    if (close(fd) != 0) saved = errno;
    if (unlink(template) != 0 && saved == 0) saved = errno;
    if (saved != 0) {
        errno = saved;
        return -1;
    }
    return 0;
}

studpad_guest_home_status studpad_prepare_guest_home(const char *base, const char *component,
                                                     char *out, size_t outSize, int *errOut) {
    if (errOut) *errOut = 0;
    if (out && outSize) out[0] = '\0';

    if (!base || !*base || !component || !*component || component[0] == '/' || !out || !outSize) {
        return STUDPAD_GUEST_HOME_INVALID;
    }

    int written = snprintf(out, outSize, "%s/%s", base, component);
    if (written < 0 || (size_t)written >= outSize) {
        out[0] = '\0';
        if (errOut) *errOut = ENAMETOOLONG;
        return STUDPAD_GUEST_HOME_PATH_TOO_LONG;
    }

    if (ensure_directory(out) != 0) {
        int saved = errno;
        struct stat info;
        if (stat(out, &info) == 0 && !S_ISDIR(info.st_mode)) {
            if (errOut) *errOut = ENOTDIR;
            out[0] = '\0';
            return STUDPAD_GUEST_HOME_NOT_DIRECTORY;
        }
        if (errOut) *errOut = saved;
        out[0] = '\0';
        return STUDPAD_GUEST_HOME_MKDIR_FAILED;
    }

    if (probe_writable(out) != 0) {
        if (errOut) *errOut = errno;
        out[0] = '\0';
        return STUDPAD_GUEST_HOME_PROBE_FAILED;
    }

    return STUDPAD_GUEST_HOME_OK;
}

const char *studpad_guest_home_status_name(studpad_guest_home_status status) {
    switch (status) {
    case STUDPAD_GUEST_HOME_OK:
        return "ok";
    case STUDPAD_GUEST_HOME_INVALID:
        return "invalid arguments";
    case STUDPAD_GUEST_HOME_PATH_TOO_LONG:
        return "path too long";
    case STUDPAD_GUEST_HOME_MKDIR_FAILED:
        return "cannot create directory";
    case STUDPAD_GUEST_HOME_NOT_DIRECTORY:
        return "path exists but is not a directory";
    case STUDPAD_GUEST_HOME_PROBE_FAILED:
        return "write probe failed";
    }
    return "unknown";
}
