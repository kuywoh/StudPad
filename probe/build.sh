#!/bin/bash
# Build the unsigned StudPad signing probe IPA. SideStore re-signs it on install.
# No Roblox binary is involved here.
set -euo pipefail
cd "$(dirname "$0")"

SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
TARGET="arm64-apple-ios16.0"
CC=(xcrun --sdk iphoneos clang -target "$TARGET" -isysroot "$SDK" -O1 -Wall)

OUT=out
APP="$OUT/Payload/StudPadProbe.app"
rm -rf "$OUT" "StudPadProbe.ipa"
mkdir -p "$APP/Frameworks/ProbeKit.framework" "$APP/Frameworks/StudioGuest.bundle"

"${CC[@]}" -fobjc-arc -framework UIKit -framework Foundation main.m -o "$APP/StudPadProbe"
"${CC[@]}" -dynamiclib -install_name @rpath/ProbeKit.framework/ProbeKit \
    probe_framework.c -o "$APP/Frameworks/ProbeKit.framework/ProbeKit"
"${CC[@]}" -bundle probe_bundle.c -o "$APP/Frameworks/StudioGuest.bundle/StudioGuest"

cp Info.plist "$APP/Info.plist"

cat > "$APP/Frameworks/ProbeKit.framework/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>ProbeKit</string>
<key>CFBundleIdentifier</key><string>com.kuywoh.studpad.probekit</string>
<key>CFBundlePackageType</key><string>FMWK</string>
<key>CFBundleShortVersionString</key><string>0.1</string>
<key>CFBundleVersion</key><string>1</string>
<key>MinimumOSVersion</key><string>16.0</string>
</dict></plist>
PLIST

cat > "$APP/Frameworks/StudioGuest.bundle/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>StudioGuest</string>
<key>CFBundleIdentifier</key><string>com.kuywoh.studpad.studioguest</string>
<key>CFBundlePackageType</key><string>BNDL</string>
<key>CFBundleShortVersionString</key><string>0.1</string>
<key>CFBundleVersion</key><string>1</string>
<key>MinimumOSVersion</key><string>16.0</string>
</dict></plist>
PLIST

echo "=== host ==="
file "$APP/StudPadProbe"
echo "=== nested ==="
file "$APP/Frameworks/ProbeKit.framework/ProbeKit" "$APP/Frameworks/StudioGuest.bundle/StudioGuest"

(cd "$OUT" && zip -qry ../StudPadProbe.ipa Payload)
echo "built $(pwd)/StudPadProbe.ipa"
