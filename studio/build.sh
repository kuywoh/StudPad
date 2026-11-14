#!/bin/bash
# Build the unsigned Studio load-probe IPA. SideStore re-signs it on install.
#
# The IPA necessarily contains the official Studio executable fetched in this job. It is uploaded only
# as a private workflow artifact for the user's own iPad; nothing is committed to git.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
WORK="$ROOT/.work/studio-probe"
rm -rf "$WORK"
mkdir -p "$WORK"

echo "=== fetching official arm64 Studio ==="
bash "$ROOT/recon/fetch_studio.sh" "" "$WORK/fetch"
APP="$(find "$WORK/fetch/app" -maxdepth 2 -name 'RobloxStudio.app' -type d -print -quit)"
[ -n "$APP" ] || { echo "no RobloxStudio.app in $WORK/fetch/app" >&2; exit 1; }
echo "Studio app: $APP"

OUT="$WORK/out"
APP_OUT="$OUT/Payload/StudPadStudioProbe.app"
rm -rf "$OUT"
mkdir -p "$APP_OUT/Frameworks" \
         "$APP_OUT/Frameworks/PlugIns/platforms" \
         "$APP_OUT/Frameworks/PlugIns/styles" \
         "$APP_OUT/Frameworks/PlugIns/imageformats"

cp Info.plist "$APP_OUT/Info.plist"

# The guest is a plain Mach-O, not a .framework: SideStore's installer validates every nested
# framework executable, and an MH_BUNDLE with LC_MAIN is not a valid framework executable.
cp "$APP/Contents/MacOS/RobloxStudio" "$APP_OUT/Frameworks/StudioKit"

# Qt as plain dylibs. The framework bundle layout is what SideStore's nested signer rejects.
for fw in "$APP/Contents/Frameworks/"*.framework; do
  name="$(basename "$fw" .framework)"
  cp "$fw/Versions/5/$name" "$APP_OUT/Frameworks/lib$name.dylib"
done

cp "$APP/Contents/MacOS/libmimalloc.3.dylib" "$APP_OUT/Frameworks/"
cp "$APP/Contents/MacOS/libfbxsdk.dylib" "$APP_OUT/"   # @executable_path/libfbxsdk.dylib
for lib in libQtitanBase.dylib libQtitanDocking.dylib libQtitanOffice2016Style.dylib; do
  [ -f "$APP/Contents/MacOS/$lib" ] && cp "$APP/Contents/MacOS/$lib" "$APP_OUT/Frameworks/"
done

cp "$APP/Contents/PlugIns/Qt5/platforms/libqoffscreen.dylib" "$APP_OUT/Frameworks/PlugIns/platforms/"
cp "$APP/Contents/PlugIns/Qt5/platforms/libqminimal.dylib" "$APP_OUT/Frameworks/PlugIns/platforms/"
cp "$APP/Contents/PlugIns/Qt5/styles/libqmacstyle.dylib" "$APP_OUT/Frameworks/PlugIns/styles/" || true
cp "$APP/Contents/PlugIns/Qt5/imageformats/libqjpeg.dylib" "$APP_OUT/Frameworks/PlugIns/imageformats/" || true
cp "$APP/Contents/PlugIns/Qt5/imageformats/libqgif.dylib" "$APP_OUT/Frameworks/PlugIns/imageformats/" || true

if [ -d "$APP/Contents/Resources" ]; then
  ditto "$APP/Contents/Resources" "$APP_OUT/Resources"
fi

cat > "$APP_OUT/qt.conf" <<'EOF'
[Paths]
Plugins = Frameworks/PlugIns
EOF

SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
VTARGET=arm64-apple-ios16.0

patch_one() {
  local f="$1"
  local main_flag="${2:-}"
  if lipo -archs "$f" | grep -q 'x86_64'; then
    lipo -thin arm64 "$f" -output "$f.arm64"
    mv "$f.arm64" "$f"
  fi
  if [ "$main_flag" = main ]; then
    python3 patch_macho.py --main "$f"
  else
    python3 patch_macho.py "$f"
  fi
  xcrun vtool -set-build-version ios 16.0 26.0 -replace -output "$f.vtool" "$f"
  mv "$f.vtool" "$f"
}

echo "=== patching guest and Qt ==="
patch_one "$APP_OUT/Frameworks/StudioKit" main
for lib in "$APP_OUT/Frameworks/"libQt*.dylib; do
  patch_one "$lib"
done
patch_one "$APP_OUT/Frameworks/libmimalloc.3.dylib"
patch_one "$APP_OUT/libfbxsdk.dylib"
for lib in "$APP_OUT/Frameworks/"libQtitan*.dylib; do
  [ -e "$lib" ] && patch_one "$lib"
done
for plugin in "$APP_OUT/Frameworks/PlugIns/platforms/"*.dylib \
              "$APP_OUT/Frameworks/PlugIns/styles/"*.dylib \
              "$APP_OUT/Frameworks/PlugIns/imageformats/"*.dylib; do
  [ -e "$plugin" ] && patch_one "$plugin"
done

echo "=== building host ==="
CC=(xcrun --sdk iphoneos clang -target "$VTARGET" -isysroot "$SDK" -O1 -fobjc-arc
    -framework UIKit -framework Foundation
    -Wl,-rpath,@executable_path/Frameworks)
"${CC[@]}" main.m -o "$APP_OUT/StudPadStudioProbe"

file "$APP_OUT/StudPadStudioProbe" "$APP_OUT/Frameworks/StudioKit"
du -sh "$APP_OUT"

echo "=== packaging ==="
chmod 755 "$APP_OUT/StudPadStudioProbe"
(cd "$OUT" && zip -qry "$WORK/StudPadStudioProbe.ipa" Payload)
python3 verify.py "$WORK/StudPadStudioProbe.ipa"
ls -l "$WORK/StudPadStudioProbe.ipa"
shasum -a 256 "$WORK/StudPadStudioProbe.ipa"
echo "built $WORK/StudPadStudioProbe.ipa"

# Tiny control IPA: same plist/host, no Studio payload. If LiveContainer cannot run this,
# the problem is the host bundle, not the 1 GB guest or zsign. It logs the expected dlopen failure.
echo "=== packaging host-only control ==="
HOST_OUT="$WORK/host-only"
HOST_APP="$HOST_OUT/Payload/StudPadHostOnly.app"
mkdir -p "$HOST_APP"
cp Info.plist "$HOST_APP/Info.plist"
cp "$APP_OUT/StudPadStudioProbe" "$HOST_APP/StudPadHostOnly"
plutil -replace CFBundleExecutable -string StudPadHostOnly "$HOST_APP/Info.plist"
plutil -replace CFBundleIdentifier -string com.kuywoh.studpadhostonly "$HOST_APP/Info.plist"
plutil -replace CFBundleDisplayName -string "StudPad Host Probe" "$HOST_APP/Info.plist"
plutil -replace CFBundleName -string "StudPad Host Probe" "$HOST_APP/Info.plist"
chmod 755 "$HOST_APP/StudPadHostOnly"
(cd "$HOST_OUT" && zip -qry "$WORK/StudPadHostOnly.ipa" Payload)
ls -l "$WORK/StudPadHostOnly.ipa"
shasum -a 256 "$WORK/StudPadHostOnly.ipa"
