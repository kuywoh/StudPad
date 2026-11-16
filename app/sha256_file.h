#ifndef STUDPAD_SHA256_FILE_H
#define STUDPAD_SHA256_FILE_H

#define STUDPAD_SHA256_HEX_LENGTH 65

int studpad_sha256_file(const char *path, char hex[STUDPAD_SHA256_HEX_LENGTH]);

#endif
