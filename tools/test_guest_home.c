#include "GuestHome.h"

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void make_base(char *path, size_t size) {
    const char *tmp = getenv("TMPDIR");
    if (!tmp || !*tmp) tmp = "/tmp";
    int written = snprintf(path, size, "%s/studpad-guest-home.XXXXXX", tmp);
    assert(written > 0 && (size_t)written < size);
    assert(mkdtemp(path) != NULL);
}

int main(void) {
    char base[PATH_MAX];
    char home[PATH_MAX];
    char second[PATH_MAX];
    int error = 0;
    make_base(base, sizeof base);

    assert(studpad_prepare_guest_home(base, "StudPadStudio", home, sizeof home, &error) ==
           STUDPAD_GUEST_HOME_OK);
    assert(error == 0);
    assert(home[0] != '\0');
    assert(strstr(home, "StudPadStudio") != NULL);

    struct stat info;
    assert(stat(home, &info) == 0);
    assert(S_ISDIR(info.st_mode));

    // A stale fixed-name probe from an older build must not make the unique probe fail.
    char stale[PATH_MAX];
    int written = snprintf(stale, sizeof stale, "%s/.studpad-write-probe", home);
    assert(written > 0 && (size_t)written < sizeof stale);
    int fd = open(stale, O_CREAT | O_WRONLY, 0600);
    assert(fd >= 0);
    assert(close(fd) == 0);

    assert(studpad_prepare_guest_home(base, "StudPadStudio", second, sizeof second, &error) ==
           STUDPAD_GUEST_HOME_OK);
    assert(error == 0);
    assert(strcmp(home, second) == 0);
    assert(access(stale, F_OK) == 0);
    assert(unlink(stale) == 0);

    // Nested components are created too, matching the Library fallback in MacShim.m.
    char nested[PATH_MAX];
    assert(studpad_prepare_guest_home(base, "Library/Application Support/StudPadStudio", nested,
                                      sizeof nested, &error) == STUDPAD_GUEST_HOME_OK);
    assert(error == 0);
    assert(stat(nested, &info) == 0);
    assert(S_ISDIR(info.st_mode));

    // Invalid arguments leave the output empty and do not touch errno-derived state.
    home[0] = 'x';
    error = 99;
    assert(studpad_prepare_guest_home(NULL, "StudPadStudio", home, sizeof home, &error) ==
           STUDPAD_GUEST_HOME_INVALID);
    assert(home[0] == '\0');
    assert(error == 0);

    error = 99;
    assert(studpad_prepare_guest_home(base, "", home, sizeof home, &error) ==
           STUDPAD_GUEST_HOME_INVALID);
    assert(home[0] == '\0');
    assert(error == 0);

    // A component that is a regular file cannot become the guest home.
    char file[PATH_MAX];
    written = snprintf(file, sizeof file, "%s/not-a-directory", base);
    assert(written > 0 && (size_t)written < sizeof file);
    fd = open(file, O_CREAT | O_WRONLY, 0600);
    assert(fd >= 0);
    assert(close(fd) == 0);
    error = 0;
    assert(studpad_prepare_guest_home(base, "not-a-directory", home, sizeof home, &error) ==
           STUDPAD_GUEST_HOME_NOT_DIRECTORY);
    assert(home[0] == '\0');
    assert(error == ENOTDIR);

    // A directory whose write bit is removed makes the unique probe fail. CI does not run as root;
    // skip the assertion if it does, because root can still create the probe.
    char read_only[PATH_MAX];
    assert(studpad_prepare_guest_home(base, "read-only", read_only, sizeof read_only, &error) ==
           STUDPAD_GUEST_HOME_OK);
    assert(chmod(read_only, 0500) == 0);
    error = 0;
    studpad_guest_home_status probe_status =
        studpad_prepare_guest_home(base, "read-only", home, sizeof home, &error);
    if (geteuid() != 0) {
        assert(probe_status == STUDPAD_GUEST_HOME_PROBE_FAILED);
        assert(home[0] == '\0');
        assert(error != 0);
    }
    assert(chmod(read_only, 0700) == 0);

    // Path truncation is rejected before anything is created.
    char too_long[4096];
    memset(too_long, 'a', sizeof too_long - 1);
    too_long[sizeof too_long - 1] = '\0';
    error = 0;
    assert(studpad_prepare_guest_home(base, too_long, home, sizeof home, &error) ==
           STUDPAD_GUEST_HOME_PATH_TOO_LONG);
    assert(home[0] == '\0');
    assert(error == ENAMETOOLONG);

    assert(strcmp(studpad_guest_home_status_name(STUDPAD_GUEST_HOME_OK), "ok") == 0);
    assert(strcmp(studpad_guest_home_status_name(STUDPAD_GUEST_HOME_PROBE_FAILED),
                  "write probe failed") == 0);
    return 0;
}
