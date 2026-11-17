#ifndef STUDPAD_ZIP_RESOURCES_H
#define STUDPAD_ZIP_RESOURCES_H

#include <stddef.h>

int studpad_extract_resources_zip(const char *zip_path,
                                  const char *destination,
                                  const char *app_bundle_name,
                                  char *error,
                                  size_t error_capacity);

#endif
