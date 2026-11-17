#define _DARWIN_C_SOURCE 1

#include "../app/sha256_file.h"

#include <CommonCrypto/CommonDigest.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define TEST_BYTES (2u * 1024u * 1024u + 37u)

typedef struct {
    const char *path;
    int result;
    char actual[STUDPAD_SHA256_HEX_LENGTH];
} HashRequest;

static void to_hex(const unsigned char *digest, char *hex) {
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) {
        hex[2 * i] = digits[digest[i] >> 4];
        hex[2 * i + 1] = digits[digest[i] & 0x0f];
    }
    hex[CC_SHA256_DIGEST_LENGTH * 2] = '\0';
}

static void *hash_on_small_stack(void *context) {
    HashRequest *request = context;
    request->result = studpad_sha256_file(request->path, request->actual);
    return NULL;
}

static void fail_test(const char *message, const char *path) {
    if (path) unlink(path);
    fputs(message, stderr);
}

int main(void) {
    char path[] = "/tmp/studpad-sha256-XXXXXX";
    int fd = mkstemp(path);
    if (fd < 0) {
        perror("mkstemp");
        return 1;
    }

    unsigned char *contents = malloc(TEST_BYTES);
    if (!contents) {
        close(fd);
        fail_test("could not allocate test contents\n", path);
        return 1;
    }
    for (size_t i = 0; i < TEST_BYTES; i++) contents[i] = (unsigned char)(i * 31u + 7u);

    FILE *output = fdopen(fd, "wb");
    int write_failed = output == NULL;
    if (output) {
        if (fwrite(contents, 1, TEST_BYTES, output) != TEST_BYTES) write_failed = 1;
        if (fclose(output) != 0) write_failed = 1;
    } else {
        close(fd);
    }
    if (write_failed) {
        free(contents);
        fail_test("could not write test file\n", path);
        return 1;
    }

    unsigned char expected_digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(contents, (CC_LONG)TEST_BYTES, expected_digest);
    free(contents);
    char expected[STUDPAD_SHA256_HEX_LENGTH];
    to_hex(expected_digest, expected);

    HashRequest request = {.path = path, .result = -1, .actual = {0}};
    pthread_attr_t attributes;
    pthread_t thread;
    if (pthread_attr_init(&attributes) != 0) {
        fail_test("could not initialize small-stack test\n", path);
        return 1;
    }
    if (pthread_attr_setstacksize(&attributes, 512u * 1024u) != 0) {
        pthread_attr_destroy(&attributes);
        fail_test("could not set small hash-thread stack\n", path);
        return 1;
    }
    if (pthread_create(&thread, &attributes, hash_on_small_stack, &request) != 0) {
        pthread_attr_destroy(&attributes);
        fail_test("could not start small-stack hash test\n", path);
        return 1;
    }
    pthread_attr_destroy(&attributes);
    if (pthread_join(thread, NULL) != 0) {
        fail_test("could not join small-stack hash test\n", path);
        return 1;
    }
    unlink(path);

    if (request.result != 0 || strcmp(request.actual, expected) != 0) {
        fprintf(stderr, "streamed hash mismatch: %.64s, expected %.64s\n",
                request.actual, expected);
        return 1;
    }

    if (studpad_sha256_file(path, request.actual) == 0) {
        fputs("missing-file hash unexpectedly succeeded\n", stderr);
        return 1;
    }

    puts("sha256 file tests passed");
    return 0;
}
