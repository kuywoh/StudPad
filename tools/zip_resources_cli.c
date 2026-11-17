#include "../app/zip_resources.h"

#include <stdio.h>

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: zip_resources_cli <package.zip> <destination> <app-bundle-name>\n");
        return 2;
    }
    char error[512];
    if (studpad_extract_resources_zip(argv[1], argv[2], argv[3], error, sizeof(error)) != 0) {
        fprintf(stderr, "%s\n", error);
        return 1;
    }
    return 0;
}
