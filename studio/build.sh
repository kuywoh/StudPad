#!/bin/bash
# Build a small StudPad installer IPA: a retargeted arm64 Studio engine and Qt runtime, with
# large matching Studio Resources downloaded by the iPad app from Roblox's CDN.
#
# Runs on a macOS runner (GitHub Actions) or any Mac with Xcode command line tools. No Apple
# developer account is needed: the IPA is ad-hoc signed with app/entitlements-sideload.plist and
# SideStore re-signs it on the iPad.
#
# Stages, so CI can show which one runs (and a stall is visible instead of one 20-minute step):
#
#   fetch      download the official arm64 Studio package into .work/studio/fetch
#   stage      copy the guest, Qt, helper dylibs and plugins into .work/studio/stage
#   retarget1  rewrite the load commands of every staged image for iOS
#   plan       compile the hand-written shim, then generate the stubs it is missing
#   retarget2  point every library the shim must absorb at libMacShim.dylib
#   link       link libMacShim.dylib
#   host       build the UIKit host app
#   check      refuse the build unless every shim-bound import is exported
#   sign       ad-hoc sign everything, carrying the sideload entitlements
#   package    zip and verify the IPA
#
#   studio/build.sh all      runs every stage in order
#   studio/build.sh <stage>  runs one
#
# No Roblox binary is committed. The package is downloaded inside the job, the IPA is a private
# workflow artifact, and everything lives under .work/ (gitignored).
set -euo pipefail
# No tool may ever wait for input: a command that reads stdin would hang the whole job.
exec < /dev/null
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
WORK="$ROOT/.work/studio"
OUT="$WORK/out"
APP="$OUT/Payload/StudPadStudio.app"
SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
TARGET="arm64-apple-ios16.0"
IOS_MIN=16.0
LOG="$ROOT/.work-build.log"

step() { printf '\n=== %s ===\n' "$*"; }

# A failed step in CI is otherwise just "exit code 1", so turn the tail of the log into error
# annotations: the run page and the public checks API then carry the actual message.
annotate_failure() {
  local status=$? line=${BASH_LINENO[0]:-?}
  echo "::error title=build.sh ($STAGE) failed at line $line::exit status $status"
  [ -f "$LOG" ] || return 0
  grep -aiE 'error|fail|cannot|can.t|not found|unsupported|refus|traceback|no such|denied|timeout' "$LOG" \
    | tail -n 8 | while IFS= read -r text; do
      text=${text//'%'/%25}
      text=${text//$'\r'/}
      echo "::error::$text"
    done || true
}
trap annotate_failure ERR

# macOS has no coreutils timeout, and a stuck tool must fail the stage instead of the job.
#
# The command runs in its own process group and a timeout kills the whole group. Killing only the
# direct child is not enough: clang leaves a cc1 process behind, that orphan inherits the step's
# stdout pipe, and `tee` then waits on it until the job's own 60-minute limit (which is exactly how
# the previous run "hung" after a compile error).
guard() {
  local secs=$1
  shift
  perl -e '
    use POSIX ();
    my $secs = shift @ARGV;
    POSIX::setpgid(0, 0);
    my $pid = fork();
    die "guard: fork failed: $!" unless defined $pid;
    if ($pid == 0) { exec @ARGV; exit 127; }
    $SIG{ALRM} = sub { kill "KILL", -getpgrp(0); };
    alarm $secs;
    waitpid($pid, 0);
    my $status = $?;
    alarm 0;
    exit($status & 127 ? 128 + ($status & 127) : $status >> 8);
  ' "$secs" "$@"
}

sdk_version() {
  local version
  version="$(plutil -extract Version raw "$SDK/SDKSettings.plist" 2>/dev/null || echo 26.0)"
  case "$version" in
    [0-9]*.[0-9]*) printf '%s' "$version" ;;
    [0-9]*) printf '%s.0' "$version" ;;
    *) printf '26.0' ;;
  esac
}

SDK_VER="$(sdk_version)"
SDK_NAME="$(plutil -extract CanonicalName raw "$SDK/SDKSettings.plist" 2>/dev/null || echo "iphoneos$SDK_VER")"

package_app() {
  local app
  app="$(find "$WORK/fetch/app" -maxdepth 2 -name 'RobloxStudio.app' -type d -print -quit 2>/dev/null || true)"
  [ -n "$app" ] || { echo "no RobloxStudio.app: run the fetch stage first" >&2; return 1; }
  printf '%s' "$app"
}

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

images() { # every Mach-O this build ships, in link order
  printf '%s\n' "$APP/Frameworks/StudioKit" "$APP/Frameworks/libMacShim.dylib"
  local f
  for f in "$APP/Frameworks/"*.dylib "$APP/Frameworks/PlugIns/"*/*.dylib "$APP/"*.dylib; do
    [ -f "$f" ] && printf '%s\n' "$f"
  done
}

# ---------------------------------------------------------------------------------------------

fetch() {
  rm -rf "$WORK"
  mkdir -p "$WORK"
  : >"$WORK/retarget.log"
  step "fetch the official Mac Studio package (arm64)"
  bash "$ROOT/recon/fetch_studio.sh" "" "$WORK/fetch"
  local app
  app="$(package_app)"
  echo "package app: $app"
  du -sh "$app" || true
}

stage_files() {
  step "stage the guest, Qt, the helper dylibs and the Qt plugins"
  local src; src="$(package_app)"
  local stage="$WORK/stage"
  mkdir -p "$stage/qt" "$stage/plugins/platforms" "$stage/plugins/styles" "$stage/plugins/imageformats"
  cp "$src/Contents/MacOS/RobloxStudio" "$stage/StudioKit"
  local dylib fw name binary plugin candidate
  for dylib in "$src/Contents/MacOS/"*.dylib; do
    [ -f "$dylib" ] && cp "$dylib" "$stage/"
  done
  for fw in "$src/Contents/Frameworks/"*.framework; do
    name="$(basename "$fw" .framework)"
    binary="$(find "$fw/Versions" -maxdepth 2 -type f -name "$name" -print -quit 2>/dev/null || true)"
    if [ -z "$binary" ]; then
      echo "  $name: no binary inside the framework, skipped"
      continue
    fi
    # Flat dylibs, not framework bundles: SideStore's installer validates the executable of every
    # nested .framework and refuses this shape.
    cp "$binary" "$stage/qt/lib$name.dylib"
  done
  for plugin in platforms/libqcocoa platforms/libqoffscreen platforms/libqminimal \
    styles/libqmacstyle imageformats/libqjpeg imageformats/libqgif; do
    candidate="$src/Contents/PlugIns/Qt5/$plugin.dylib"
    if [ -f "$candidate" ]; then
      cp "$candidate" "$stage/plugins/$(dirname "$plugin")/"
    else
      echo "  plugin $plugin not present in this build"
    fi
  done
  ls -1 "$stage/qt" | head -n 20
}

retarget1() {
  step "retarget pass 1: platform, paths, shim redirect, MH_DYLIB"
  local stage="$WORK/stage"
  mkdir -p "$APP/Frameworks/PlugIns/platforms" "$APP/Frameworks/PlugIns/styles" \
    "$APP/Frameworks/PlugIns/imageformats"
  retarget "$stage/StudioKit" "$APP/Frameworks/StudioKit"
  local lib plugin
  for lib in "$stage/qt/"*.dylib; do retarget "$lib" "$APP/Frameworks/$(basename "$lib")"; done
  for lib in "$stage/"*.dylib; do
    [ -f "$lib" ] || continue
    # Studio loads libfbxsdk from @executable_path, the rest through @rpath/Frameworks.
    case "$(basename "$lib")" in
      libfbxsdk*) retarget "$lib" "$APP/$(basename "$lib")" ;;
      *) retarget "$lib" "$APP/Frameworks/$(basename "$lib")" ;;
    esac
  done
  for plugin in "$stage/plugins"/*/*.dylib; do
    retarget "$plugin" "$APP/Frameworks/PlugIns/$(basename "$(dirname "$plugin")")/$(basename "$plugin")"
  done

  # Keep Studio's explicit mi_* APIs, but disable macOS-only process-wide malloc/free interposition.
  python3 "$ROOT/tools/disable_macho_interpose.py" "$APP/Frameworks/libmimalloc.3.dylib"

  local src; src="$(package_app)"
  python3 "$ROOT/studio/write_studio_manifest.py" \
    "$WORK/fetch/fetch.txt" "$WORK/fetch/studio.zip" "$APP/StudioPackage.plist"
  echo "Studio Resources will be downloaded on the iPad at first launch."
  cat >"$APP/qt.conf" <<'CONF'
[Paths]
Plugins = Frameworks/PlugIns
CONF

  # The iOS frameworks these images link. The shim re-exports them for two reasons: an AppKit import
  # that macOS served through a re-export still needs a real implementation, and a reroute moves
  # every bind that shares an ordinal opcode with a stub, which can include an entire library.
  python3 "$ROOT/tools/check_binds.py" "$APP" --sdk "$SDK" --frameworks > "$WORK/reexports.txt"
  echo "re-exporting $(wc -l < "$WORK/reexports.txt" | tr -d ' ') iOS frameworks"
}

plan() {
  step "compile the hand-written shim (to learn what it already provides)"
  local cc=(xcrun --sdk iphoneos clang -target "$TARGET" -isysroot "$SDK" -O1 -fobjc-arc
    -I"$ROOT/shim" -Wno-deprecated-declarations)
  guard 300 "${cc[@]}" -c "$ROOT/shim/MacShim.m" -o "$WORK/MacShim.o"

  step "plan the stubs: what Studio needs that the iOS SDK does not export"
  local shipped=() lib
  for lib in "$APP/Frameworks/"*.dylib "$APP/Frameworks/StudioKit" "$APP/"*.dylib \
    "$APP/Frameworks/PlugIns/"*/*.dylib; do
    [ -f "$lib" ] || continue
    [ "$(basename "$lib")" = "libMacShim.dylib" ] && continue
    shipped+=("$lib")
  done
  local reexports=() framework
  if [ -f "$WORK/reexports.txt" ]; then
    while IFS= read -r framework; do
      [ -n "$framework" ] && reexports+=("$framework")
    done < "$WORK/reexports.txt"
  fi
  guard 1800 python3 "$ROOT/tools/plan_shim.py" \
    --sdk "$SDK" \
    --guest "$APP/Frameworks/StudioKit" \
    --shipped "${shipped[@]}" \
    --reexport ${reexports[@]+"${reexports[@]}"} \
    --have-object "$WORK/MacShim.o" \
    --stubs "$WORK/stubs.c" \
    --objc "$WORK/stubs_objc.m" \
    --reroute "$WORK/reroute.txt" \
    --absorb "$WORK/absorb.txt" \
    --absorb-out "$WORK/absorb.txt" \
    --reexport-flags "$WORK/link-reexports.txt" \
    --report "$WORK/shim-plan.txt"
}

retarget2() {
  step "retarget pass 2: put the libraries iOS is missing symbols from behind the shim"
  local binary
  for binary in "$APP/Frameworks/StudioKit" "$APP/Frameworks/"*.dylib \
    "$APP/Frameworks/PlugIns/"*/*.dylib "$APP/"*.dylib; do
    [ -f "$binary" ] || continue
    retarget "$binary" "$binary.rerouted" --absorb "$WORK/absorb.txt"
    mv "$binary.rerouted" "$binary"
  done

  # Plan again against the final ordinals. Rerouting rewrites an ordinal opcode in place and several
  # imports can share one, so a library's binds can move to the shim as a group; those symbols must
  # be exported by the shim (through a re-export or a stub), and only this second pass can see them.
  plan
}

link() {
  step "compile the shim sources"
  local sources=("$WORK/stubs.c" "$WORK/stubs_objc.m")
  [ -f "$WORK/stubs_asm.s" ] && sources+=("$WORK/stubs_asm.s")
  wc -l "${sources[@]}" || true
  local cc=(xcrun --sdk iphoneos clang -target "$TARGET" -isysroot "$SDK" -c -fobjc-arc -O1
    -I"$ROOT/shim" -Wno-deprecated-declarations)
  local objs=() src obj
  for src in "$ROOT/shim/MacShim.m" "${sources[@]}"; do
    obj="$WORK/obj-$(basename "$src").o"
    guard 600 "${cc[@]}" "$src" -o "$obj"
    echo "  $(basename "$src") -> $(wc -c <"$obj" | tr -d ' ') bytes"
    objs+=("$obj")
  done

  step "link libMacShim.dylib"
  # The plan writes the exact -framework/-reexport_library set: the iOS frameworks the images link
  # plus every library it had to absorb. Keeping the list in one place is what makes plan and link
  # agree about what the shim exports.
  local linked=() token
  while IFS= read -r token; do
    [ -n "$token" ] && linked+=("$token")
  done < "$WORK/link-reexports.txt"
  [ "${#linked[@]}" -gt 0 ] || { echo "no re-export flags from the plan" >&2; return 1; }
  guard 600 xcrun --sdk iphoneos clang -target "$TARGET" -isysroot "$SDK" -dynamiclib \
    -install_name @rpath/libMacShim.dylib \
    -compatibility_version 9999.0.0 -current_version 9999.0.0 \
    "${linked[@]}" \
    "${objs[@]}" -o "$APP/Frameworks/libMacShim.dylib"
}

host() {
  step "build the host app"
  guard 300 xcrun --sdk iphoneos clang -target "$TARGET" -isysroot "$SDK" -O1 \
    -I"$ROOT/app" -c "$ROOT/app/zip_resources.c" -o "$WORK/zip_resources.o"
  guard 300 xcrun --sdk iphoneos clang -target "$TARGET" -isysroot "$SDK" -O1 \
    -I"$ROOT/app" -c "$ROOT/app/sha256_file.c" -o "$WORK/sha256_file.o"
  guard 300 xcrun --sdk iphoneos clang -target "$TARGET" -isysroot "$SDK" -O1 -fobjc-arc \
    -I"$ROOT/shim" -I"$ROOT/app" -framework UIKit -framework Foundation \
    -L"$APP/Frameworks" -lMacShim -Wl,-rpath,@executable_path/Frameworks \
    -Wl,-platform_version,ios,"$IOS_MIN","$SDK_VER" \
    "$ROOT/app/starter.m" "$WORK/zip_resources.o" "$WORK/sha256_file.o" -lz -o "$APP/StudPadStudio"
  chmod 755 "$APP/StudPadStudio"

  cp "$ROOT/app/Info.plist" "$APP/Info.plist"
  plutil -replace DTPlatformVersion -string "$SDK_VER" "$APP/Info.plist"
  plutil -replace DTSDKName -string "$SDK_NAME" "$APP/Info.plist"
  plutil -replace MinimumOSVersion -string "$IOS_MIN" "$APP/Info.plist"
  local build_number="${GITHUB_RUN_NUMBER:-0}" src version
  plutil -replace CFBundleVersion -string "$build_number" "$APP/Info.plist"
  src="$(package_app)"
  version="$(plutil -extract CFBundleShortVersionString raw "$src/Contents/Info.plist" 2>/dev/null || true)"
  [ -n "$version" ] && plutil -replace CFBundleShortVersionString -string "$version" "$APP/Info.plist"
  return 0
}

check() {
  step "check every import the shim has to satisfy"
  guard 1800 python3 "$ROOT/tools/check_binds.py" "$APP" --sdk "$SDK"
  python3 "$ROOT/tools/disable_macho_interpose.py" --check "$APP/Frameworks/libmimalloc.3.dylib"
}

sign() {
  step "ad-hoc sign, carrying the entitlements the IPA asks for"
  local entitlements="$ROOT/app/entitlements-sideload.plist" binary
  python3 "$ROOT/studio/validate_entitlements.py" "$entitlements"
  for binary in "$APP/Frameworks/StudioKit" "$APP/Frameworks/"*.dylib "$APP/"*.dylib \
    "$APP/Frameworks/PlugIns/"*/*.dylib; do
    [ -f "$binary" ] || continue
    guard 300 codesign -f -s - "$binary" 2>/dev/null || echo "  ad-hoc sign failed: $binary"
  done

  # The entitlements that matter (get-task-allow for StikDebug, increased-memory-limit for
  # GetMoreRam) are read by SideStore from the main executable's signature. Signing the *bundle* here
  # is not needed and it fails while validating Studio's copied resources as nested code, so the
  # executable is what gets the entitlements and the bundle signature is best effort.
  #
  # codesign seals the enclosing bundle when it signs a code object inside one and then rejects the
  # bundle's resources as unsigned nested code, so the executable is signed outside the bundle and
  # moved back. The identifier is given explicitly because it would otherwise come from the
  # temporary file's name.
  cp "$APP/StudPadStudio" "$WORK/StudPadStudio.sign"
  guard 300 codesign -f -s - -i com.kuywoh.studpadstudio --entitlements "$entitlements" \
    "$WORK/StudPadStudio.sign"
  mv "$WORK/StudPadStudio.sign" "$APP/StudPadStudio"
  chmod 755 "$APP/StudPadStudio"
  local signed_entitlements="$WORK/signed-entitlements.plist"
  codesign -d --entitlements :- "$APP/StudPadStudio" >"$signed_entitlements" 2>/dev/null || {
    echo "ERROR: could not read the main executable's signed entitlements" >&2
    return 1
  }
  python3 "$ROOT/studio/validate_entitlements.py" "$signed_entitlements"
  echo "  main executable signature carries all three requested sideload entitlements"
  return 0
}

package() {
  step "package"
  ( cd "$OUT" && guard 1800 zip -qry "$WORK/StudPadStudio.ipa" Payload )
  python3 "$ROOT/studio/verify.py" "$WORK/StudPadStudio.ipa"
  ls -lh "$WORK/StudPadStudio.ipa"
  shasum -a 256 "$WORK/StudPadStudio.ipa" | tee "$WORK/StudPadStudio.ipa.sha256"
}

STAGE="${1:-all}"
case "$STAGE" in
  fetch) fetch ;;
  stage) stage_files ;;
  retarget1) retarget1 ;;
  plan) plan ;;
  retarget2) retarget2 ;;
  link) link ;;
  host) host ;;
  check) check ;;
  sign) sign ;;
  package) package ;;
  all)
    fetch; stage_files; retarget1; plan; retarget2; link; host; check; sign; package
    echo "built $WORK/StudPadStudio.ipa"
    ;;
  *)
    echo "unknown stage '$STAGE' (fetch|stage|retarget1|plan|retarget2|link|host|check|sign|package|all)" >&2
    exit 2
    ;;
esac


