#include "zip_resources.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <zlib.h>

#define ZIP_EOCD 0x06054b50u
#define ZIP_CENTRAL 0x02014b50u
#define ZIP_LOCAL 0x04034b50u
#define ZIP_FLAG_ENCRYPTED 0x0001u
#define ZIP_METHOD_STORE 0u
#define ZIP_METHOD_DEFLATE 8u
#define CHUNK_SIZE 65536u

static uint16_t le16(const unsigned char *p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static uint32_t le32(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static int zip_error(char *buffer, size_t capacity, const char *format, ...) {
    if (buffer && capacity) {
        va_list args;
        va_start(args, format);
        vsnprintf(buffer, capacity, format, args);
        va_end(args);
    }
    return -1;
}

static int read_exact(FILE *file, void *data, size_t size) {
    return fread(data, 1, size, file) == size;
}

static int make_directory(const char *path) {
    struct stat info;
    if (mkdir(path, 0755) == 0) return 0;
    if (errno != EEXIST || stat(path, &info) != 0 || !S_ISDIR(info.st_mode)) return -1;
    return 0;
}

static int make_parents(const char *path) {
    char copy[PATH_MAX];
    size_t length = strlen(path);
    if (length == 0 || length >= sizeof(copy)) return -1;
    memcpy(copy, path, length + 1);
    for (char *p = copy + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            if (make_directory(copy) != 0) return -1;
            *p = '/';
        }
    }
    return 0;
}

static const char *unsafe_relative_path_reason(const char *path, size_t length) {
    if (!length) return "empty path";
    if (path[0] == '/') return "absolute path";
    if (memchr(path, '\\', length)) return "backslash";
    if (memchr(path, '\0', length)) return "NUL byte";

    size_t start = 0;
    for (size_t i = 0; i <= length; i++) {
        if (i == length || path[i] == '/') {
            size_t part = i - start;
            if (!part) return "empty path segment";
            if (part == 1 && path[start] == '.') return "dot path segment";
            if (part == 2 && path[start] == '.' && path[start + 1] == '.')
                return "parent traversal";
            start = i + 1;
        }
    }
    return NULL;
}

static void escape_archive_path(char *output, size_t capacity,
                                const char *path, size_t length) {
    static const char hex[] = "0123456789abcdef";
    if (!capacity) return;
    size_t used = 0;
    for (size_t i = 0; i < length; i++) {
        unsigned char byte = (unsigned char)path[i];
        size_t needed = byte >= 0x20 && byte <= 0x7e && byte != '\\' ? 1 : 4;
        if (used + needed >= capacity) {
            if (capacity - used > 3) {
                memcpy(output + used, "...", 3);
                used += 3;
            }
            break;
        }
        if (needed == 1) {
            output[used++] = (char)byte;
        } else {
            output[used++] = '\\';
            output[used++] = 'x';
            output[used++] = hex[byte >> 4];
            output[used++] = hex[byte & 0x0f];
        }
    }
    output[used] = '\0';
}

static int write_all(int fd, const unsigned char *data, size_t length) {
    while (length) {
        ssize_t written = write(fd, data, length);
        if (written < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        data += written;
        length -= (size_t)written;
    }
    return 0;
}

static int write_entry(FILE *archive, uint64_t data_offset, uint32_t compressed_size,
                       uint32_t expected_size, uint16_t method, uint32_t expected_crc,
                       const char *output_path, char *error, size_t error_capacity) {
    if (make_parents(output_path) != 0)
        return zip_error(error, error_capacity, "cannot create resource directory: %s", output_path);
    int fd = open(output_path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0644);
    if (fd < 0)
        return zip_error(error, error_capacity, "cannot create resource file %s: %s",
                         output_path, strerror(errno));
    FILE *out = fdopen(fd, "wb");
    if (!out) {
        close(fd);
        unlink(output_path);
        return zip_error(error, error_capacity, "cannot open resource output %s", output_path);
    }

    unsigned char input[CHUNK_SIZE], output[CHUNK_SIZE];
    uint32_t remaining = compressed_size;
    uint64_t produced_total = 0;
    uLong crc = crc32(0L, Z_NULL, 0);
    int failed = 0;

    if (method == ZIP_METHOD_STORE) {
        if (compressed_size != expected_size || fseek(archive, (long)data_offset, SEEK_SET) != 0)
            failed = 1;
        while (!failed && remaining) {
            size_t amount = remaining > sizeof(input) ? sizeof(input) : remaining;
            if (!read_exact(archive, input, amount) ||
                write_all(fileno(out), input, amount) != 0) {
                failed = 1;
                break;
            }
            crc = crc32(crc, input, (uInt)amount);
            produced_total += amount;
            remaining -= (uint32_t)amount;
        }
    } else if (method == ZIP_METHOD_DEFLATE) {
        z_stream stream;
        memset(&stream, 0, sizeof(stream));
        if (fseek(archive, (long)data_offset, SEEK_SET) != 0 ||
            inflateInit2(&stream, -MAX_WBITS) != Z_OK) {
            failed = 1;
        } else {
            int ended = 0;
            while (!failed && !ended) {
                if (stream.avail_in == 0 && remaining) {
                    size_t amount = remaining > sizeof(input) ? sizeof(input) : remaining;
                    if (!read_exact(archive, input, amount)) {
                        failed = 1;
                        break;
                    }
                    stream.next_in = input;
                    stream.avail_in = (uInt)amount;
                    remaining -= (uint32_t)amount;
                }
                stream.next_out = output;
                stream.avail_out = sizeof(output);
                int status = inflate(&stream, Z_NO_FLUSH);
                size_t amount = sizeof(output) - stream.avail_out;
                if (amount) {
                    if (produced_total + amount > expected_size ||
                        write_all(fileno(out), output, amount) != 0) {
                        failed = 1;
                        break;
                    }
                    crc = crc32(crc, output, (uInt)amount);
                    produced_total += amount;
                }
                if (status == Z_STREAM_END) ended = 1;
                else if (status != Z_OK ||
                         (stream.avail_in == 0 && remaining == 0 && amount == 0)) failed = 1;
            }
            if (!failed && (remaining != 0 || stream.avail_in != 0 ||
                            produced_total != expected_size || (uint32_t)crc != expected_crc))
                failed = 1;
            inflateEnd(&stream);
        }
    } else {
        failed = 1;
    }

    if (method == ZIP_METHOD_STORE && !failed &&
        (produced_total != expected_size || (uint32_t)crc != expected_crc)) failed = 1;
    if (fflush(out) != 0) failed = 1;
    if (fclose(out) != 0) failed = 1;
    if (failed) {
        unlink(output_path);
        return zip_error(error, error_capacity, "invalid or corrupt Studio resource: %s",
                         output_path);
    }
    return 0;
}

int studpad_extract_resources_zip(const char *zip_path, const char *destination,
                                  const char *app_bundle_name, char *error,
                                  size_t error_capacity) {
    if (error && error_capacity) error[0] = '\0';
    if (!zip_path || !destination || !app_bundle_name || !*app_bundle_name ||
        strchr(app_bundle_name, '/') || strchr(app_bundle_name, '\\') ||
        strstr(app_bundle_name, ".."))
        return zip_error(error, error_capacity, "invalid archive or app bundle name");

    char prefix[PATH_MAX];
    int prefix_size = snprintf(prefix, sizeof(prefix), "%s/Contents/Resources/",
                               app_bundle_name);
    if (prefix_size < 0 || (size_t)prefix_size >= sizeof(prefix))
        return zip_error(error, error_capacity, "app bundle name is too long");

    FILE *archive = fopen(zip_path, "rb");
    if (!archive) return zip_error(error, error_capacity, "cannot open Studio package: %s",
                                   strerror(errno));
    if (fseek(archive, 0, SEEK_END) != 0) {
        fclose(archive);
        return zip_error(error, error_capacity, "cannot seek Studio package");
    }
    long file_size = ftell(archive);
    if (file_size < 22) {
        fclose(archive);
        return zip_error(error, error_capacity, "Studio package is not a ZIP archive");
    }

    size_t tail_size = (size_t)(file_size < 65557 ? file_size : 65557);
    long tail_offset = file_size - (long)tail_size;
    unsigned char *tail = malloc(tail_size);
    if (!tail || fseek(archive, tail_offset, SEEK_SET) != 0 ||
        !read_exact(archive, tail, tail_size)) {
        free(tail);
        fclose(archive);
        return zip_error(error, error_capacity, "cannot read Studio package directory");
    }
    long eocd_index = -1;
    for (long i = (long)tail_size - 22; i >= 0; i--) {
        if (le32(tail + i) == ZIP_EOCD &&
            i + 22 + le16(tail + i + 20) == (long)tail_size) {
            eocd_index = i;
            break;
        }
    }
    if (eocd_index < 0) {
        free(tail);
        fclose(archive);
        return zip_error(error, error_capacity, "Studio package has no ZIP directory");
    }
    const unsigned char *eocd = tail + eocd_index;
    uint16_t disk = le16(eocd + 4), directory_disk = le16(eocd + 6);
    uint16_t disk_entries = le16(eocd + 8), entries = le16(eocd + 10);
    uint32_t directory_size = le32(eocd + 12), directory_offset = le32(eocd + 16);
    uint64_t eocd_offset = (uint64_t)tail_offset + (uint64_t)eocd_index;
    free(tail);

    if (disk || directory_disk || disk_entries != entries || entries == 0xffffu ||
        directory_size == 0xffffffffu || directory_offset == 0xffffffffu ||
        (uint64_t)directory_offset + directory_size > eocd_offset ||
        fseek(archive, (long)directory_offset, SEEK_SET) != 0) {
        fclose(archive);
        return zip_error(error, error_capacity, "unsupported or invalid Studio ZIP directory");
    }
    if (make_parents(destination) != 0 || make_directory(destination) != 0) {
        fclose(archive);
        return zip_error(error, error_capacity, "cannot create Studio resource staging folder");
    }

    unsigned long extracted = 0;
    for (uint32_t index = 0; index < entries; index++) {
        unsigned char header[46];
        if (!read_exact(archive, header, sizeof(header)) || le32(header) != ZIP_CENTRAL) {
            fclose(archive);
            return zip_error(error, error_capacity, "invalid ZIP central directory entry");
        }
        uint16_t flags = le16(header + 8), method = le16(header + 10);
        uint32_t crc = le32(header + 16), compressed_size = le32(header + 20);
        uint32_t uncompressed_size = le32(header + 24);
        uint16_t name_size = le16(header + 28), extra_size = le16(header + 30);
        uint16_t comment_size = le16(header + 32);
        uint32_t attributes = le32(header + 38), local_offset = le32(header + 42);
        if (!name_size || compressed_size == 0xffffffffu || uncompressed_size == 0xffffffffu ||
            local_offset == 0xffffffffu || local_offset >= directory_offset) {
            fclose(archive);
            return zip_error(error, error_capacity, "unsupported ZIP entry format");
        }
        char *name = malloc((size_t)name_size + 1);
        if (!name || !read_exact(archive, name, name_size)) {
            free(name);
            fclose(archive);
            return zip_error(error, error_capacity, "truncated ZIP entry name");
        }
        name[name_size] = '\0';
        if (memchr(name, '\0', name_size)) {
            free(name);
            fclose(archive);
            return zip_error(error, error_capacity, "invalid ZIP entry name");
        }
        long skip = (long)extra_size + (long)comment_size;
        if (fseek(archive, skip, SEEK_CUR) != 0) {
            free(name);
            fclose(archive);
            return zip_error(error, error_capacity, "truncated ZIP entry metadata");
        }
        long next_entry = ftell(archive);
        if (next_entry < 0) {
            free(name);
            fclose(archive);
            return zip_error(error, error_capacity, "cannot read ZIP directory position");
        }

        size_t prefix_length = (size_t)prefix_size;
        if (strncmp(name, prefix, prefix_length) != 0) {
            free(name);
            continue;
        }
        const char *relative = name + prefix_length;
        size_t relative_length = strlen(relative);
        int is_directory = name[name_size - 1] == '/';
        if (is_directory && relative_length) relative_length--;
        /* The Resources/ entry itself has no relative suffix, but is a safe directory. */
        if (relative_length == 0 && is_directory && name_size == prefix_length) {
            free(name);
            continue;
        }
        const char *unsafe_reason = unsafe_relative_path_reason(relative, relative_length);
        if (unsafe_reason) {
            char display_path[160];
            escape_archive_path(display_path, sizeof(display_path), relative, relative_length);
            int result = zip_error(error, error_capacity,
                                   "unsafe Studio resource path at ZIP entry %u (%s): %s",
                                   (unsigned int)index, unsafe_reason, display_path);
            free(name);
            fclose(archive);
            return result;
        }
        unsigned int file_mode = (attributes >> 16) & 0170000u;
        if (file_mode == 0120000u || (file_mode && file_mode != 0100000u &&
                                      file_mode != 0040000u)) {
            free(name);
            fclose(archive);
            return zip_error(error, error_capacity, "unsupported special Studio resource file");
        }
        if (is_directory || file_mode == 0040000u) {
            char output_path[PATH_MAX];
            int n = snprintf(output_path, sizeof(output_path), "%s/%.*s",
                             destination, (int)relative_length, relative);
            free(name);
            if (n < 0 || (size_t)n >= sizeof(output_path) ||
                make_parents(output_path) != 0 || make_directory(output_path) != 0) {
                fclose(archive);
                return zip_error(error, error_capacity, "cannot create Studio resource folder");
            }
            continue;
        }
        if ((flags & ZIP_FLAG_ENCRYPTED) ||
            (method != ZIP_METHOD_STORE && method != ZIP_METHOD_DEFLATE)) {
            free(name);
            fclose(archive);
            return zip_error(error, error_capacity, "unsupported Studio resource compression");
        }
        unsigned char local[30];
        if (fseek(archive, (long)local_offset, SEEK_SET) != 0 ||
            !read_exact(archive, local, sizeof(local)) || le32(local) != ZIP_LOCAL) {
            free(name);
            fclose(archive);
            return zip_error(error, error_capacity, "invalid local ZIP header");
        }
        uint16_t local_name_size = le16(local + 26), local_extra_size = le16(local + 28);
        if (local_name_size != name_size) {
            free(name);
            fclose(archive);
            return zip_error(error, error_capacity, "ZIP local and central names differ");
        }
        char *local_name = malloc((size_t)local_name_size + 1);
        if (!local_name || !read_exact(archive, local_name, local_name_size)) {
            free(name);
            free(local_name);
            fclose(archive);
            return zip_error(error, error_capacity, "truncated local ZIP name");
        }
        local_name[local_name_size] = '\0';
        int names_match = memcmp(local_name, name, name_size) == 0;
        free(local_name);
        if (!names_match) {
            free(name);
            fclose(archive);
            return zip_error(error, error_capacity, "ZIP local and central names differ");
        }
        uint64_t data_offset = (uint64_t)local_offset + 30u +
                               (uint64_t)local_name_size + (uint64_t)local_extra_size;
        if (data_offset + compressed_size > directory_offset) {
            free(name);
            fclose(archive);
            return zip_error(error, error_capacity, "ZIP resource points outside file data");
        }

        char output_path[PATH_MAX];
        int n = snprintf(output_path, sizeof(output_path), "%s/%.*s",
                         destination, (int)relative_length, relative);
        if (n < 0 || (size_t)n >= sizeof(output_path) ||
            write_entry(archive, data_offset, compressed_size, uncompressed_size,
                        method, crc, output_path, error, error_capacity) != 0) {
            free(name);
            fclose(archive);
            if (error && error_capacity && !error[0])
                snprintf(error, error_capacity, "cannot write Studio resource");
            return -1;
        }
        extracted++;
        free(name);

        if (fseek(archive, next_entry, SEEK_SET) != 0) {
            fclose(archive);
            return zip_error(error, error_capacity, "cannot continue ZIP directory scan");
        }
    }
    fclose(archive);
    if (!extracted) return zip_error(error, error_capacity, "no Roblox Studio resources found");
    return 0;
}
