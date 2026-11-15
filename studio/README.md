# StudPad Studio build

Builds an installable iPad app from Roblox's **official arm64 macOS Studio**, without Xcode on your
own machine: GitHub Actions runs the macOS steps and uploads an unsigned IPA that SideStore signs.

This is a bring-up build, not a finished port. It gets Studio's Mach-O images loaded on iOS and logs
where it stops; see [../docs/cyport.md](../docs/cyport.md) for the architecture and the open problem
(Qt's Cocoa platform plugin).

## What the job does

1. `recon/fetch_studio.sh` — resolve the live Mac Studio build and download
   `mac/arm64/version-<hash>-RobloxStudioApp.zip` from Roblox's CDN (inside the runner only).
2. Stage `Contents/MacOS/RobloxStudio` as `Frameworks/StudioKit`, the nine Qt 5.15 frameworks as
   flat `libQt*.dylib` (SideStore refuses nested `.framework` executables), the Qt plugins Studio
   needs (`libqcocoa`, `libqoffscreen`, `libqminimal`, `libqmacstyle`, jpeg/gif), `libmimalloc`,
   `libfbxsdk`, `libQtitan*` and `Contents/Resources`.
3. `tools/ios_retarget.py` pass 1 — platform macOS → iOS, versioned framework paths → iOS flat
   paths, AppKit/Cocoa/Carbon/ApplicationServices/ForceFeedback/DiskArbitration/ColorSync/IOKit/
   OpenGL → `@rpath/libMacShim.dylib`, the guest `MH_EXECUTE` → `MH_DYLIB` with `LC_MAIN` kept,
   duplicate load commands collapsed and import ordinals renumbered.
4. `tools/plan_shim.py` — every undefined symbol of the guest and the shipped libraries, minus what
   the iOS SDK exports, minus what the hand-written shim implements. That difference becomes
   `stubs.c` (a logging stub per C symbol), `stubs_objc.m` (a class per missing AppKit/Carbon class,
   inheriting `MSStubObject`) and the reroute list.
5. `tools/ios_retarget.py` pass 2 — rewrite the import ordinals of those stubbed symbols so they
   bind to the shim (two-level namespace).
6. Link `libMacShim.dylib` (shim + stubs, re-exporting Foundation, UIKit, CoreFoundation,
   CoreGraphics, QuartzCore, CoreText, ImageIO, Security, Metal, GameController,
   UniformTypeIdentifiers, AudioToolbox).
7. Build the host (`app/starter.m`): a normal UIKit app with a scene, a log view, and the shim's
   `studpad_guest_start()` on the main thread.
8. `tools/check_binds.py` — refuses the build unless every symbol bound to the shim is exported by
   it and no import still names a macOS framework.
9. Ad-hoc sign everything, sign the bundle with `app/entitlements-sideload.plist`, zip, then
   `verify.py` checks the Mach-O shape of the guest, QtCore, the shim and the host.

## Running it

```shell
bash studio/build.sh          # on a Mac with Xcode command line tools
```

or, without a Mac: Actions → **studio-build** → *Run workflow*. The IPA is the
`StudPadStudio-ipa` artifact (3-day retention); `studio-build-report-*` carries `build.log`,
`shim-plan.txt` and `retarget.log`.

## What the device log tells you

`Documents/studio.log`, also shown on screen. In order:

- `dlopen returned …; images N -> M` — dyld accepted the retargeted Studio plus Qt.
- `calling Studio main` — the guest entry point ran.
- `[stub] X()` / `[miss] -[Class method]` — the first thing Studio wanted that only a stub provides.
  That line is the next thing to implement in `shim/MacShim.m`.

`Documents/studpad.plist` overrides the Qt setup while bringing the UI up:

```xml
<dict>
  <key>QtPlatform</key><string>offscreen</string>   <!-- offscreen | minimal | cocoa -->
  <key>QtStyle</key><string>fusion</string>
</dict>
```

`cocoa` is the goal and the hard one: it puts Qt's Cocoa platform plugin on top of the AppKit slice.

## Limits, stated plainly

- Qt runs on its **offscreen** platform: Studio can construct and lay out its UI but has nothing to
  draw into yet, and gets no input.
- Stubs return 0 without type information. A constant (`NSFooMode`) arrives as a function, a
  float-returning function returns 0 in the integer register. A crash there is expected; the log
  names the symbol.
- Studio's `RobloxCrashHandler`, `StudioMCP` and installer are not shipped: iOS forbids launching
  bundled executables. Whether Studio needs one before its first window is unknown.
- Nothing here is verified on a device by CI. CI proves packaging and linking only.
