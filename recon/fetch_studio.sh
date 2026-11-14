#!/bin/bash
# Fetch the official macOS Roblox Studio app package inside the runner.
#
# Usage: recon/fetch_studio.sh [version-hash] [work-dir]
#
# The small RobloxStudio.zip on setup.rbxcdn.com is the installer (RobloxStudioInstaller.app);
# the app itself is version-<hash>-RobloxStudioApp.zip (~600 MB at the time of writing).
# Nothing here is committed; the package stays in the work dir, which is gitignored.
set -euo pipefail

VERSION_INPUT="${1:-}"
DEST="${2:-.work}"
MAC="https://setup.rbxcdn.com/mac"
MIN_BYTES=$((100 * 1024 * 1024))

mkdir -p "$DEST"

say() { printf '%s\n' "$*"; }

if [ -n "$VERSION_INPUT" ]; then
  UPLOAD="$VERSION_INPUT"
  VERSION="(pinned)"
else
  JSON="$(curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 30 \
    "https://clientsettingscdn.roblox.com/v2/client-version/MacStudio")"
  UPLOAD="$(printf '%s' "$JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["clientVersionUpload"])')"
  VERSION="$(printf '%s' "$JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')"
fi

case "$UPLOAD" in
  version-*) ;;
  *) UPLOAD="version-$UPLOAD" ;;
esac

URL="$MAC/$UPLOAD-RobloxStudioApp.zip"
say "Studio version: $VERSION"
say "Package URL: $URL"

curl -fL --retry 3 --retry-delay 5 --connect-timeout 30 \
  -o "$DEST/studio.zip" "$URL"

BYTES="$(wc -c < "$DEST/studio.zip" | tr -d ' ')"
say "Downloaded $BYTES bytes"
if [ "$BYTES" -lt "$MIN_BYTES" ]; then
  say "ERROR: $BYTES bytes is the installer bootstrapper, not the Studio app."
  say "       Refusing to analyze it as if it were Studio."
  exit 1
fi

rm -rf "$DEST/app"
mkdir -p "$DEST/app"
ditto -x -k "$DEST/studio.zip" "$DEST/app"

APP="$(find "$DEST/app" -maxdepth 2 -name '*.app' -type d -print -quit)"
if [ -z "$APP" ]; then
  say "ERROR: no .app bundle inside the package. Top level:"
  find "$DEST/app" -maxdepth 2 -print
  exit 1
fi
say "App: $APP"
du -sh "$APP"

{
  echo "version=$VERSION"
  echo "upload=$UPLOAD"
  echo "url=$URL"
  echo "bytes=$BYTES"
  echo "sha256=$(shasum -a 256 "$DEST/studio.zip" | awk '{print $1}')"
  echo "app=$APP"
} > "$DEST/fetch.txt"
