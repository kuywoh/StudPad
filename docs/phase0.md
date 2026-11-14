# Phase 0 — Recon report

Status: **complete for static recon**. No device build has been attempted, and nothing in this
report has been run on an iPad.

Scope: can the official macOS arm64 Roblox Studio build be loaded on an iPad Air M4 (iPadOS 26)
by rewriting its load commands to point at shim libraries, as Slashplayed does for World of
Warcraft?

Short answer: **the architecture is viable, but the UI stack is a much larger problem than
Slashplayed's, and one Qt/Cocoa question decides the project.** Details below.

## 1. GitHub and repository

- GitHub identity on this machine: **`kuywoh`** (`gh auth status`, account active; scopes include
  `repo` and `workflow`).
- `Kuywoh/StudPad` already exists: **private, empty** at the start of this phase. No new repository
  is needed.
- This phase added the recon workflow and reports to it:
  - runs: `43566233556` (Intel default path, diagnostic) and `43566545065` (arm64, used below)
  - the artifacts are text only; the 587 MB package stays in the runner's `.work/`, which is
    gitignored. No Roblox binary is committed.

## 2. What Slashplayed needs a Mac for

Slashplayed has three parts: a Mac companion (SwiftUI), a Windows/Linux companion (Rust), and a
device app whose executable is a launcher plus shims plus an app-extension JIT helper.

### Build time

Needs macOS with Apple tooling, but **not necessarily the user's Mac**:

- Xcode 27 with iOS/visionOS SDKs and the Metal toolchain, XcodeGen, `xcodebuild`.
- Clang for the shim dylibs; Rust (idevice, spapple); Python 3 for recon/generation.
- Signing/provisioning: Xcode with an Apple ID, or the `isideload` + zsign path used by the
  Windows/Linux companion.

All of that can run on GitHub-hosted macOS runners. The user's Windows PC needs only git, a text
editor, and a browser.

The current runner image has **Xcode 26.3** with the iOS 26 SDK (plus Xcode 16.4 as the default).
Phase 1 must select 26.3 (`xcode-select`) because the shims need `-target arm64-apple-ios26.0`.
Xcode 27 is not installed on the runner; it is not needed for iPadOS 26.

### Setup time (no Mac, with the Windows/Linux companion)

- Pair/trust over USB (Apple Devices or iTunes driver on Windows; usbmuxd on Linux), enable
  Developer Mode.
- Apple ID sign-in (GSA/SRP, 2FA), anisette, team selection; register the device; create App IDs
  for the app and the `.helper`; set capabilities (`increased-memory-limit`, and
  `extended-virtual-addressing` on a paid team); make/collect a development certificate; download
  both profiles.
- Sign with zsign; install through `installation_proxy`; copy the RemotePairing record, developer
  disk image, and Apple token into the container over AFC.
- Free team limits: 7-day profiles, 3 free-team apps per device, 10 App IDs per week; the helper
  uses an App ID but not one of the three app slots.

### Run time (no Mac)

- The launcher starts UIKit first on iOS (the 20 s scene watchdog), then the helper attaches, then
  the loader maps the unchanged, unsigned client.
- Everything after install runs on the device: no Mac, no Xcode, no host.

## 3. LocalDevVPN and the TXM helper

**What problem it solves.** On M2-and-later devices, TXM (and on M1, PPL) decides what may execute.
No certificate a third party can obtain grants `MAP_JIT` or writable-then-executable pages. WoW's
client rewrites its own `__TEXT` at startup, so it needs executable memory that iOS will not grant
normally.

**What works instead (measured by Slashplayed):**

- A page a debugger has written to stays `r-x` with maximum protection `rwx`.
- Code written later through a separate read-write alias (`vm_remap`) executes at the original
  address, including the app's own signed `__TEXT`, and keeps working after the debugger detaches.
- A page made writable in place can never execute again. So the loader reserves the client span,
  asks the debugger to prepare all of `__TEXT` (one `brk #0xf00d` stop, one byte per 16 KB page),
  detaches, then services the client's rewrites through the alias.

**What the helper is.** A second process is required because a process cannot service its own
debugger stops. It is a classic app extension (`PlugIns/SPJitHelper.appex`) claiming Apple's AR
viewer extension point, started by the launcher through private `NSExtension` calls. It links
`idevice` and, through LocalDevVPN's loopback tunnel (`10.7.0.1:49152`), starts `debugserver`,
mounts the developer disk image when needed (personalized with Apple's TSS), attaches, services
the prepare stop, and detaches. A launch takes about 1.5 s from start to attached.

**Does it work without a Mac?** Yes at run time, with conditions:

- LocalDevVPN must be installed and on at every launch (it does not restore itself after a
  restart). The launcher opens `localdevvpn://enable?scheme=…` and waits for a TCP connect.
- The iPad needs a RemotePairing record made **once over USB**. iOS refuses to pair with itself,
  so this cannot be made on-device; the Mac companion or the Windows/Linux companion (`idevice`,
  lockdown `remotepairingdeviced`) makes it. Never log or commit this record.
- The developer disk image must be present (the companion copies it; on iOS 26.4+ the cryptex
  survives a reboot).
- Developer Mode must be on, and the app must be development-signed with `get-task-allow`.

**Consequence for Studio.** The helper is only needed if Studio actually needs executable memory
or self-modification. Static recon found **no** `MAP_JIT`, `pthread_jit_write_protect_np`,
`JITWriteSeparateHeaps`, or JavaScriptCore JIT imports; Studio ships no QtQml/QtQuick frameworks,
and Luau is an interpreter. The `com.apple.security.cs.allow-jit` entitlement is present on the
macOS signature, but it is a macOS entitlement and is not grantable on iOS. **Working hypothesis:
the TXM helper, LocalDevVPN, the extension, and the free-team App ID cost are all unnecessary for
Studio.** This is unverified and must be confirmed at runtime before Phase 1 commits to the
loader design; a `brk`/`mprotect` path or a `mmap(PROT_EXEC)` at startup would invalidate it.

## 4. Studio package recon (official CDN, 2026-11-14)

| Fact | Value |
|---|---|
| Live Mac Studio version | `0.747.0.7471481` |
| Upload hash | `version-5b06061c96124bdc` |
| **Default `mac/` package** | **x86_64 only**: engine, Qt frameworks and Cocoa plugin are Intel; only the installer and `libfbxsdk` are universal |
| **Apple Silicon package** | `https://setup.rbxcdn.com/mac/arm64/version-5b06061c96124bdc-RobloxStudioApp.zip`, 587,096,305 bytes, SHA-256 `8f68525e00c31d968732a06dd583988b74e5aab0149feae222c12499d7ea62cb` |
| App | `RobloxStudio.app`, `com.Roblox.RobloxStudio`, 0.747.0.7471481 |
| Main executable | 205,723,584 bytes, arm64, minOS 11.0, SDK 26.2 |
| Mach-O files | 28 (28 arm64; installer and FBX also carry x86_64) |
| Qt | 5.15 (QtCore short version); 9 frameworks: Core, Gui, Widgets, Network, Sql, Xml, PrintSupport, DBus, Concurrent |
| Load commands | `LC_MAIN`, **no chained fixups**, no `LC_ENCRYPTION_INFO` cryptid, no `__RESTRICT`, **no hardened runtime** |
| Entitlements | `com.apple.security.cs.allow-jit`, `device.audio-input`, `device.camera`, `network.client` |
| Embedded browser | WebKit classes imported by the main executable; no CEF/Electron/QtWebEngine |
| Renderer surface | OpenGL + `NSOpenGLContext`/`NSOpenGLPixelFormat` and Metal device/descriptor calls in the main executable; QtGui/libqcocoa also use Metal |
| Bundled executables | `RobloxCrashHandler`, `NativeDialog`, `StudioMCP`, a 71 KB nested `RobloxStudio.app` relauncher, and the 23.6 MB universal `RobloxStudioInstaller.app` |
| Static anti-tamper evidence | None found: no `SecCodeCheckValidity`, no `csops`, no obfuscation/protector strings. `SecRequirementCreateWithString` is imported only by QtCore; one `warden` string is not evidence. Runtime checks remain unverified. |

The **x86_64 default is a trap**: downloading `setup.rbxcdn.com/mac/RobloxStudioApp.zip` and
concluding "Studio is Intel-only" would be wrong. Roblox's installer selects an arch-specific
path from a table embedded in its binary (`"arch": "arm64" → "pathExtension": "mac/arm64"`), and
the arm64 app is a separate 587 MB package. The earlier 11 MB `RobloxStudio.zip` is only the
installer and is correctly refused by `recon/fetch_studio.sh`.

## 5. Import gap against the iPadOS 26 SDK

2,589 unique imports from system libraries:

- **2,139 available** from the same iOS library or its re-exports.
- **63 exported by a different iOS library** (15 of the AppKit ones come from private
  `UIKitCore`/`UIFoundation`, e.g. `NSColor`, `NSFont`, attributed-string keys).
- **387 missing** — the shim surface.

| Rank | Area | Imports (missing) | iPadOS replacement | Shim must provide | Difficulty |
|---|---|---|---|---|---|
| 1 | **AppKit** (Qt's Cocoa platform plugin is built on it) | 199 (184): 46 classes, 10 metaclasses, 77 constants, 51 functions | UIKit scenes/windows/views, UIEvent, GCMouse, UIMenu, UIDocumentPicker, UIPasteboard | `NSApplication`/`NSWindow`/`NSView`/`NSMenu`, panels, tracking areas, text input context, fonts/colors, pasteboard, app lifecycle | **Very high** |
| 2 | **Qt 5.15 Cocoa QPA integration** (`libqcocoa.dylib`) | not a symbol row | UIKit | Either make Qt's Cocoa plugin run over the AppKit shim, or build a Qt 5.15 iOS QPA plugin against Studio's exact Qt build; backing store, screen, input, menus, GL/Metal | **Very high / decisive** |
| 3 | **Desktop OpenGL / NSOpenGL** | 36 (2): `glClearDepth`, `glPolygonMode`; 34 exist in OpenGLES | OpenGLES + EAGL, or force a Metal path | `NSOpenGLContext`/`NSOpenGLPixelFormat`, GL dispatch, GLSL ES port, no compatibility-profile features | **High, conditionally blocking** |
| 4 | **Subprocess helpers** | `posix_spawn`, `posix_spawnp`, `fork`, `execve`, `NSTask`, `NSWorkspace` in main, CrashHandler, StudioMCP | none — iOS denies launching bundled executables | Run helpers in-process, disable/reimplement crash reporting, installer/updater, MCP | **High if boot-critical**, medium otherwise |
| 5 | **WebKit** | 8 classes/constants in the main executable | iOS `WKWebView` + UIKit hosting | macOS WebKit semantics, process pool, data store, user scripts; out-of-process content | **Medium-high, feature-specific** |
| 6 | **CoreGraphics display/events** | 150 (37): `CGDisplay*`, `CGEvent*`, cursor warp, event taps | `UIScreen`, `UIScene`, GCKeyboard/GCMouse, UITouch; no event taps | One virtual display, event synthesis, cursor association/warp | **Medium** (Slashplayed precedent) |
| 7 | **ApplicationServices** (printing/pasteboard) | 75 (75): `PM*`, `Pasteboard*`, `HIShape` | `UIPasteboard`; printing stubs | Print session no-ops, pasteboard bridge, shape stub | **Low-medium** (print/export lost) |
| 8 | **Carbon** | 13 (13): TIS input sources, HITheme | UIKit text input; no HITheme | US keyboard layout, `UCKeyTranslate`, no-op window frame/theme | **Low-medium** (Slashplayed code) |
| 9 | **Security** | 68 (10): legacy keychain, `SecTrustSettings`, SSL DH params | `SecItem`, CommonCrypto, `SecTrust` | Keychain shims, trust settings, bundled roots | **Medium-low** |
| 10 | **CoreVideo** | 36 (6): `CVDisplayLink*` | `CADisplayLink` | Display link replacement | **Low-medium** (Slashplayed precedent) |
| 11 | **ForceFeedback** | 13 (13) | GameController haptics, or none | `FF*` no-ops | **Low** |
| 12 | **Foundation/CoreServices extras** | 6 + 13: AppleScript, `NSUserNotification`, `IconRef`, LaunchServices, UTCollator | UserNotifications, UTType, UIDocumentPicker | Stubs/limited implementations | **Low** |
| 13 | **libSystem aliases** | 9: `$INODE64`, `_select$1050` | libSystem | Symbol aliases | **Trivial** |
| 14 | **DiskArbitration / libcups / ColorSync / IOKit / libobjc** | 4 / 4 / 1 / 1 / 1 | stubs | Volume/print/display stubs, `_objc_msgSend_stret` alias | **Trivial** |
| 15 | **Audio** | 33 (0 missing; AudioUnit resolves via AudioToolboxCore) | RemoteIO / AudioToolbox | HAL output unit, no microphone, session handling | **Low-medium** if audio preview is needed |
| 16 | **Metal** | 11 (0 missing) | Metal | macOS-only device properties/observer, layer hosting | **Low** if used |

`available` does not mean behaviour-compatible: CoreFoundation, CoreText, Foundation, Metal and
Audio all exist on iOS but have platform differences that only show at runtime.

## 6. Feasibility assessment

**What is now proven:**

- A native **arm64** Studio app exists and is reachable from Roblox's official CDN; the arm64
  package is separate from the Intel default path.
- The app is a plain arm64 `MH_EXECUTE` with `LC_MAIN`, **no chained fixups**, **no hardened
  runtime**, **no `__RESTRICT`**, and no encrypted segment. A Slashplayed-style loader
  (`spguest`) is applicable; so is re-signing for iOS.
- The iPadOS 26 SDK is available on the CI runner (Xcode 26.3).
- No static evidence of an integrity/anti-tamper gate. This does not prove there is none, and it
  does not authorize defeating one; if a runtime check blocks loading, the project stops there.
- The executable-memory problem that forces Slashplayed's JIT helper **probably does not apply**
  here: no JIT/exec-memory API imports, no QML/JS engine, Luau is interpreted.

**What is not proven, and can kill the approach:**

1. **Qt 5.15 Cocoa QPA over a UIKit-backed AppKit shim.** Studio is a Qt Widgets application
   (plus Qtitan ribbon/docking). Its entire UI goes through `libqcocoa.dylib`, which imports 199
   AppKit symbols and expects a real `NSApplication`/`NSWindow`/`NSView` event loop, native menus,
   panels, tracking areas, text input, and either `NSOpenGLContext` or Metal layers. Slashplayed
   shims AppKit for a game window; making a desktop Qt QPA plugin behave over UIKit is a different
   order of work. The fallback — building Qt's iOS QPA plugin for Studio's exact Qt 5.15 build —
   needs matching Qt sources, configuration and ABI, and is likely its own project.
2. **Renderer path.** Static imports show both desktop GL and Metal. If Studio's viewport uses
   desktop GL through `NSOpenGLContext`, the shim must provide an EAGL/GLES surface and the
   engine's shaders must work on GLES (no compatibility profile, no geometry shaders). If it uses
   Metal, this risk mostly disappears. **Runtime evidence is required.**
3. **Startup subprocesses.** The main executable imports `posix_spawn`/`fork`/`execve` and
   `NSTask`. If a helper is launched before the window appears (crash handler, installer/updater,
   MCP), iOS will deny it. Which call sites are on the boot path is unknown.
4. **WebKit surfaces.** If asset store/login/docs use the embedded WebView on the boot path,
   the iOS WebKit hosting work becomes urgent rather than optional.
5. **UI fidelity and memory.** Studio is a desktop IDE; text input, menus, docking, file dialogs
   and 196 MB of code plus Qt are a much heavier footprint than a game client. The iPad Air M4
   has headroom, but jetsam and thermal behavior are untested.

**Non-technical risk.** This is an unsupported platform and a re-signed build. Roblox's terms and
enforcement policy were not reviewed here, and account action is possible (Slashplayed carries a
similar warning for Battle.net). Treat it as a policy risk to confirm before device testing, not as
a technical blocker.

**Verdict.** Not infeasible. But it is materially harder than Slashplayed, and the decisive
unknown is the Qt/Cocoa-to-UIKit boundary, not the Mach-O mechanics. Building the full Phase 1
pipeline before answering that would risk weeks of work on the wrong loader/shim shape.

## 7. Recommended next step (not done in Phase 0)

A bounded **Phase 1a spike**, before the full pipeline:

1. Build a minimal iOS 26 host app plus a loader for the arm64 Studio executable (spguest-shaped:
   map, bind, register with ObjC/unwinder, call `LC_MAIN`), with generated logging stubs and the
   smallest AppKit/UIKit shim that can bring up a `UIWindowScene`.
2. Run it on the iPad and capture where it stops: does `main` reach Qt's `NSApplicationMain`?
   Does it spawn a helper? Does it create an `NSOpenGLContext` or a `CAMetalLayer`? Does it touch
   WebKit before the first window?
3. Only then decide: continue with AppKit-over-UIKit, or pivot to a Qt iOS QPA plugin, or stop.

Estimated CI cost for that spike: 3–5 macOS runs, roughly 1–2 minutes of runner time each
(~10–20 billed minutes per run at the 10× multiplier), plus the user's sideload/run cycle. No
Apple credentials are needed in CI if the unsigned IPA is signed by the user's sideloader.

## Sources

- Slashplayed (MIT): <https://github.com/paulstraw/slashplayed> — README, `docs/architecture.md`,
  `docs/research.md`, `docs/internals/loading.md`, `docs/internals/shims.md`,
  `docs/internals/host-tool.md`, `docs/setup-without-a-mac.md`, `apps/client/spvpn.m`.
- Roblox official endpoints used by the workflow:
  `https://clientsettingscdn.roblox.com/v2/client-version/MacStudio`,
  `https://setup.rbxcdn.com/mac/arm64/<upload>-RobloxStudioApp.zip`.
- Roblox DevForum, "Native Support for Apple Silicon" (2023-07-20), and the community note that
  the Apple Silicon Studio installer lives under `setup.rbxcdn.com/channel/zmacarm64/mac/arm64/`
  (the current package is served under `mac/arm64/`).
