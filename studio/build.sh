#!/bin/bash
# Build the StudPad Studio IPA: the official arm64 macOS Studio, retargeted for iOS dyld, loaded by
# a UIKit host through libMacShim.dylib.
#
# Runs on a macOS runner (GitHub Actions) or any Mac with Xcode command line tools. It needs no
# Apple developer account: the IPA is ad-hoc signed with app/entitlements-sideload.plist and
# SideStore re-signs it on the iPad.
#
# No Roblox binary is committed. The package is downloaded inside the job, the IPA is a private
# workflow artifact, and everything lives under .work/ (gitignored).
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
WORK="$ROOT/.work/studio"
OUT="$WORK/out"
APP="$OUT/Payload/StudPadStudio.app"
SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
TARGET="arm64-apple-ios16.0"
SDK_VER="$(plutil -extract Version raw "$SDK/SDKSettings.plist" 2>/dev/null || echo 26.0)"
SDK_NAME="$(plutil -extract CanonicalName raw "$SDK/SDKSettings.plist" 2>/dev/null || echo "iphoneos$SDK_VER")"
case "$SDK_VER" in [0-9]*.[0-9]*) ;; [0-9]*) SDK_VER="$SDK_VER.0" ;; *) SDK_VER="26.0" ;; esac
IOS_MIN=16.0

step() { printf '\n=== %s ===\n' "$*"; }

retarget() { # src dst [extra ios_retarget args]
  local src="$1" dst="$2"
  shift 2
  python3 "$ROOT/tools/ios_retarget.py" --minos "$IOS_MIN" --sdk "$SDK_VER" "$@" "$src" "$dst" \
    >>"$WORK/retarget.log" 2>&1 || {
      echo "retarget failed for $src:"
      tail -n 20 "$WORK/retarget.log"
      exit 1
    }
}

rm -rf "$WORK"
mkdir -p "$WORK" "$APP/Frameworks/PlugIns/platforms" "$APP/Frameworks/PlugIns/styles" \
  "$APP/Frameworks/PlugIns/imageformats"
: >"$WORK/retarget.log"

step "fetch the official Mac Studio package (arm64)"
bash "$ROOT/recon/fetch_studio.sh" "" "$WORK/fetch"
SRC="$(find "$WORK/fetch/app" -maxdepth 2 -name 'RobloxStudio.app' -type d -print -quit)"
[ -n "$SRC" ] || { echo "no RobloxStudio.app in the downloaded package"; exit 1; }
echo "package app: $SRC"
du -sh "$SRC" || true

step "stage the guest, Qt, the helper dylibs and the Qt plugins"
STAGE="$WORK/stage"
mkdir -p "$STAGE/qt" "$STAGE/plugins/platforms" "$STAGE/plugins/styles" "$STAGE/plugins/imageformats"
cp "$SRC/Contents/MacOS/RobloxStudio" "$STAGE/StudioKit"
for dylib in "$SRC/Contents/MacOS/"*.dylib; do
  [ -f "$dylib" ] && cp "$dylib" "$STAGE/"
done
for fw in "$SRC/Contents/Frameworks/"*.framework; do
  name="$(basename "$fw" .framework)"
  binary="$(find "$fw/Versions" -maxdepth 2 -type f -name "$name" -print -quit 2>/dev/null || true)"
  if [ -z "$binary" ]; then
    echo "  $name: no binary inside the framework, skipped"
    continue
  fi
  # Flat dylibs, not framework bundles: SideStore's installer validates the executable of every
  # nested .framework and refuses this shape.
  cp "$binary" "$STAGE/qt/lib$name.dylib"
done
for plugin in platforms/libqcocoa platforms/libqoffscreen platforms/libqminimal \
  styles/libqmacstyle imageformats/libqjpeg imageformats/libqgif; do
  candidate="$SRC/Contents/PlugIns/Qt5/$plugin.dylib"
  if [ -f "$candidate" ]; then
    cp "$candidate" "$STAGE/plugins/$(dirname "$plugin")/"
  else
    echo "  plugin $plugin not present in this build"
  fi
done
ls -1 "$STAGE/qt" "$STAGE/plugins"/* | head -40

step "retarget pass 1: platform, paths, shim redirect, MH_DYLIB"
retarget "$STAGE/StudioKit" "$APP/Frameworks/StudioKit"
for lib in "$STAGE/qt/"*.dylib; do
  retarget "$lib" "$APP/Frameworks/$(basename "$lib")"
done
for lib in "$STAGE/"*.dylib; do
  [ -f "$lib" ] || continue
  # Studio loads libfbxsdk from @executable_path, the rest through @rpath/Frameworks.
  case "$(basename "$lib")" in
    libfbxsdk*) retarget "$lib" "$APP/$(basename "$lib")" ;;
    *) retarget "$lib" "$APP/Frameworks/$(basename "$lib")" ;;
  esac
done
for plugin in "$STAGE/plugins"/*/*.dylib; do
  retarget "$plugin" "$APP/Frameworks/PlugIns/$(basename "$(dirname "$plugin")")/$(basename "$plugin")"
done

if [ -d "$SRC/Contents/Resources" ]; then
  ditto "$SRC/Contents/Resources" "$APP/Resources"
fi
cat >"$APP/qt.conf" <<'CONF'
[Paths]
Plugins = Frameworks/PlugIns
CONF

step "compile the hand-written shim (to learn what it already provides)"
CC=(xcrun --sdk iphoneos clang -target "$TARGET" -isysroot "$SDK" -O1 -fobjc-arc
  -I"$ROOT/shim" -Wno-deprecated-declarations)
"${CC[@]}" -c "$ROOT/shim/MacShim.m" -o "$WORK/MacShim.o"

step "plan the stubs: what Studio needs that the iOS SDK does not export"
SHIPPED=()
for lib in "$APP/Frameworks/"*.dylib "$APP/Frameworks/StudioKit" "$APP/"*.dylib; do
  [ -f "$lib" ] || continue
  [ "$(basename "$lib")" = "libMacShim.dylib" ] && continue
  SHIPPED+=("$lib")
done
python3 "$ROOT/tools/plan_shim.py" \
  --sdk "$SDK" \
  --guest "$APP/Frameworks/StudioKit" \
  --shipped "${SHIPPED[@]}" \
  --have-object "$WORK/MacShim.o" \
  --stubs "$WORK/stubs.c" \
  --objc "$WORK/stubs_objc.m" \
  --reroute "$WORK/reroute.txt" \
  --report "$WORK/shim-plan.txt"

step "retarget pass 2: bind the stubbed imports to the shim"
for binary in "$APP/Frameworks/StudioKit" "$APP/Frameworks/"*.dylib \
  "$APP/Frameworks/PlugIns/"*/*.dylib; do
  [ -f "$binary" ] || continue
  retarget "$binary" "$binary.rerouted" --reroute "$WORK/reroute.txt"
  mv "$binary.rerouted" "$binary"
done

step "link libMacShim.dylib"
STUB_SOURCES=("$WORK/stubs.c" "$WORK/stubs_objc.m")
[ -f "$WORK/stubs_asm.s" ] && STUB_SOURCES+=("$WORK/stubs_asm.s")
xcrun --sdk iphoneos clang -target "$TARGET" -isysroot "$SDK" -dynamiclib -fobjc-arc -O1 \
  -I"$ROOT/shim" -install_name @rpath/libMacShim.dylib \
  -compatibility_version 9999.0.0 -current_version 9999.0.0 \
  -framework Foundation -framework UIKit -framework CoreGraphics -framework QuartzCore \
  -framework CoreFoundation -framework Security -framework Metal -framework CoreText \
  -framework ImageIO -framework GameController -framework UniformTypeIdentifiers \
  -framework AudioToolbox \
  -Wl,-reexport_framework,Foundation -Wl,-reexport_framework,UIKit \
  -Wl,-reexport_framework,CoreFoundation -Wl,-reexport_framework,CoreGraphics \
  -Wl,-reexport_framework,QuartzCore -Wl,-reexport_framework,CoreText \
  -Wl,-reexport_framework,ImageIO -Wl,-reexport_framework,Security \
  -Wl,-reexport_framework,Metal -Wl,-reexport_framework,GameController \
  -Wl,-reexport_framework,UniformTypeIdentifiers -Wl,-reexport_framework,AudioToolbox \
  "$ROOT/shim/MacShim.m" "${STUB_SOURCES[@]}" -o "$APP/Frameworks/libMacShim.dylib"

step "build the host app"
"${CC[@]}" -I"$ROOT/shim" -framework UIKit -framework Foundation \
  -L"$APP/Frameworks" -lMacShim -Wl,-rpath,@executable_path/Frameworks \
  -Wl,-platform_version,ios,"$IOS_MIN","$SDK_VER" \
  "$ROOT/app/starter.m" -o "$APP/StudPadStudio"
chmod 755 "$APP/StudPadStudio"

cp "$ROOT/app/Info.plist" "$APP/Info.plist"
plutil -replace DTPlatformVersion -string "$SDK_VER" "$APP/Info.plist"
plutil -replace DTSDKName -string "$SDK_NAME" "$APP/Info.plist"
plutil -replace MinimumOSVersion -string "$IOS_MIN" "$APP/Info.plist"
plutil -replace CFBundleShortVersionString -string \
  "$(plutil -extract CFBundleShortVersionString raw "$SRC/Contents/Info.plist" 2>/dev/null || echo 0.0)" \
  "$APP/Info.plist" 2>/dev/null || true

step "check every import the shim has to satisfy"
python3 "$ROOT/tools/check_binds.py" "$APP"

step "ad-hoc sign, carrying the entitlements the IPA asks for"
# Nested images first, then the bundle: codesign seals what it finds inside.
for binary in "$APP/Frameworks/StudioKit" "$APP/Frameworks/StudPadStudio" \
  "$APP/Frameworks/"*.dylib "$APP/"*.dylib "$APP/Frameworks/PlugIns/"*/*.dylib; do
  [ -f "$binary" ] || continue
  codesign -f -s - "$binary" 2>/dev/null || echo "  ad-hoc sign failed: $binary"
done
codesign -f -s - --entitlements "$ROOT/app/entitlements-sideload.plist" "$APP"
codesign -d --entitlements - "$APP" 2>&1 | sed -n '1,40p' || true

step "package"
(cd "$OUT" && zip -qry "$WORK/StudPadStudio.ipa" Payload)
python3 "$ROOT/studio/verify.py" "$WORK/StudPadStudio.ipa"
ls -lh "$WORK/StudPadStudio.ipa"
shasum -a 256 "$WORK/StudPadStudio.ipa" | tee "$WORK/StudPadStudio.ipa.sha256"
echo "built $WORK/StudPadStudio.ipa"
