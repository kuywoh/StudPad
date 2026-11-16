#include "sha256_file.h"

#include <CommonCrypto/CommonDigest.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

#define SHA256_CHUNK_SIZE (256u * 1024u)

int studpad_sha256_file(const char *path, char hex[STUDPAD_SHA256_HEX_LENGTH]) {
    if (!path || !hex) {
        errno = EINVAL;
        return -1;
    }

    FILE *input = fopen(path, "rb");
    if (!input) return -1;

    unsigned char *buffer = malloc(SHA256_CHUNK_SIZE);
    if (!buffer) {
        int saved_errno = errno;
        fclose(input);
        errno = saved_errno;
        return -1;
    }

    CC_SHA256_CTX context;
    int result = -1;
    if (CC_SHA256_Init(&context) != 1) {
        errno = EIO;
        goto done;
    }

    size_t count;
    while ((count = fread(buffer, 1, SHA256_CHUNK_SIZE, input)) > 0) {
        if (CC_SHA256_Update(&context, buffer, (CC_LONG)count) != 1) {
            errno = EIO;
            goto done;
        }
    }
    if (ferror(input)) {
        errno = EIO;
        goto done;
    }

    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    if (CC_SHA256_Final(digest, &context) != 1) {
        errno = EIO;
        goto done;
    }
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < sizeof(digest); i++) {
        hex[2 * i] = digits[digest[i] >> 4];
        hex[2 * i + 1] = digits[digest[i] & 0x0f];
    }
    hex[sizeof(digest) * 2] = '\0';
    result = 0;

done: {
    int saved_errno = errno;
    free(buffer);
    if (fclose(input) != 0 && result == 0) {
        saved_errno = errno;
        result = -1;
    }
    if (result != 0) errno = saved_errno;
    return result;
}
}
