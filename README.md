# StudPad

Bring-up of the official **arm64 macOS Roblox Studio** on an **iPad Air M4 (iPadOS 26)**, built
entirely in GitHub Actions (no Xcode on your machine) and sideloaded with SideStore.

Studio's Mac build is ordinary arm64 code, so it does not need emulation: it needs iOS dyld to accept
its Mach-O header, a `libMacShim.dylib` for the macOS frameworks it imports, and a UIKit app around
it. That is the same three-part architecture [CyPort](https://github.com/Thijs2004/CyPort) uses to
run a Mac game on iPhone/iPad, and [Slashplayed](https://github.com/paulstraw/slashplayed) uses for a
Mac game client. See [docs/cyport.md](docs/cyport.md).

**Status: CI builds a smaller installer IPA; iPad runtime behavior is unverified.** The signed IPA
contains the retargeted Studio engine and Qt runtime. On first launch, StudPad downloads the matching
official Studio package from Roblox's Mac CDN, verifies its pinned SHA-256, and extracts only the large
Resources folder into app storage. This reduces the install package; it still downloads the Studio
content before launch. The desktop `NSOpenGLContext` remains a logged stub, so a working viewport is
not established.
[docs/phase0.md](docs/phase0.md) has the static analysis and the feasibility verdict.

The setup screen checks whether the installed profile includes Increased Memory Limit and offers a
GetMoreRam walkthrough. GetMoreRam updates the Apple ID's app profile; refresh or reinstall StudPad
after adding the capability. The app also offers a StikDebug handoff using its bundle ID and running
process ID. Pair StikDebug and assign its current `universal.js` script first. JIT is optional: static
inspection found no Studio JIT imports, and StikDebug is only a diagnostic/runtime option.

Studio's allocator is not optional. Its executable links `libmimalloc.3.dylib`, whose
`__DATA,__interpose` table makes `malloc`/`free` resolve to `mi_malloc`/`mi_free`, and StudioKit
calls `mi_*` directly as well — on macOS that is one heap. dyld only reads `__interpose` from images
loaded at launch, so the build links that dylib into the host executable. `dlopen`ing it instead
leaves Qt on `libsystem_malloc` and Studio on mimalloc, and the first free across the two heaps
aborts inside `libsystem_malloc` during StudioKit's dyld initialisers.

Studio's `~` comes from the passwd entry, not from `NSHomeDirectory()`: StudioKit imports
`getpwuid`/`getpwuid_r`, QtCore `getpwuid_r` and QtWidgets `getpwnam_r`. iOS reports `/var/mobile`
there, so Studio tried to create `/var/mobile/Library/Roblox`, the sandbox refused that `mkdir`, and
Studio aborted before its first window. The shim interposes those four calls for the current user
only and reports the app container instead, and pins `HOME` and `CFFIXED_USER_HOME` to it so
every home lookup the guest makes agrees.

AppKit's globals have to be real data, not stubs. `NSApp`, the `*Notification` names, the
`*PboardType` names and `NSAppKitVersionNumber` are variables the guest loads a pointer out of; a
generated *function* under one of those names hands Studio that function's machine code, which
shows up as a message to a wild object far from the cause. `shim/MacShim.m` defines each one Studio
binds, and `tools/plan_shim.py` now lists any global-shaped name it would still stub as a function.

## Build it

Actions → **studio-build** → *Run workflow* (or push to `shim/`, `app/`, `tools/`, `studio/`).

The job downloads the official arm64 Studio package in CI, retargets and signs the engine, and
places a version-pinned CDN URL, package size and SHA-256 in the IPA. It omits the large Resources
folder from the installer. The app downloads the matching package and extracts those resources on
first launch. Text reports are uploaded even when the build fails.

## Install it (SideStore, free Apple ID)

1. SideStore installed and refreshing (see <https://docs.sidestore.io/>).
2. Install the IPA from the workflow artifact (extract the ZIP wrapper first).
3. On first launch, tap **Download Studio from Roblox** and keep StudPad open until setup finishes.
   The download uses the official version-pinned Roblox CDN package and stores only Studio Resources
   in app support; allow free space for the package download and extracted files.
4. Use the in-app **Set up GetMoreRam** walkthrough if memory is constrained. After adding Increased
   Memory Limit for `com.kuywoh.studpadstudio`, refresh or reinstall StudPad in SideStore.
5. JIT is optional. If runtime logs show an executable-memory issue, use **Enable JIT with StikDebug**.
   Pair StikDebug first and assign its current `universal.js` script to StudPad; the handoff opens
   StikDebug for the running StudPad process.

Open **StudPad Studio** and read the log in Files → On My iPad → StudPad Studio → `studio.log`.
The app creates that folder on launch, even before Studio starts. If a setup-screen build crashes
inside Studio, launch StudPad again and tap **Share log with developer**; it shares `studio.log` and
`last-crash.txt` (the signal, registers and backtrace from the failed launch). If Files still shows
no folder, use Settings → Privacy & Security → Analytics & Improvements → Analytics Data → a
`StudPadStudio-*.ips` entry, or pull `studio.log` over USB with `pymobiledevice3`/`idevicesyslog`.
After a Studio view appears, the log panel is hidden so it does not cover the app; tap **Logs** to
open it again. The useful lines include:

```
debugger attached: yes|no
JIT: executable mmap granted|refused (errno …)
memory: 1234 MB available to this process      # current headroom; not the per-app limit
allocator: malloc(64) -> mimalloc heap …       # libsystem_malloc here means Qt and Studio mix heaps
guest home: /var/mobile/Containers/Data/…/    # Studio's ~; the line below says what it used to be
dlopen returned 0x…; images 3 -> 14            # dyld accepted Studio and the Qt dylibs
screen: UIScreen bounds 1024x1366 pt …         # 320x480 here means iPhone compatibility mode
screen: NSScreen frame 1024x1366 pt …          # what Qt's cocoa plugin uses for its screen
[shim] executable path /…/RobloxStudio.app/Contents/MacOS/RobloxStudio  # Studio's install base
calling Studio main
[shim] NSColor extended: … palette method(s)  # AppKit's colour palette, answered over UIKit
[shim] NSWindow(UIWindow) … scene=0x…         # Qt created a window
[alert] runModal: style=0 buttons=[OK] message="…" informative="…" from libqcocoa…
[stub] … / [miss] -[NSView …] from StudioKit… # the next API to implement, with its caller
[miss] +[NSColor …]                           # an AppKit class method nobody implements yet
[miss] … repeated 3742 times …                # one line per event, not one per call
[log] … repeated 3742 time(s) in total        # written when the process ends
[shim] exit marker: atexit ran | exit(0) …    # absent means a signal or a kill
Studio main returned 0 (stub calls: …)        # absent with the markers above means it is still running
```

A repeated selector used to print a line per call: build 97 logged `-[NSAlert setMessageText:]`
3,742 times and nothing else. Each distinct miss or dialog is now described once — with the caller
and the value that identifies it — and only counted afterwards. Qt's dialogs are real: the shim
implements the AppKit dialog API over `UIAlertController`, answers `runModal` with the default
button rather than blocking Studio's launch, and shows the first three over Studio's window so the
text is readable on the device. When a launch ends on its own, the log now says which way: an
`exit()` line, an `atexit` line, the host's crash file for a signal, a memory warning before a
jetsam kill, or none of those for a kill.

Studio needs the iPad's own canvas. `UIDeviceFamily` in `Info.plist` lists iPads, and `verify.py`
refuses a build without it: an iPhone-only app runs letterboxed in a 320x480 canvas, which is
exactly the `QRect(0,0 320x480)` build 97's Qt reported.

Studio also has to be told where it is installed. It resolves its installation as
`QCoreApplication::applicationDirPath() + "/../Resources/AppSettings.xml"`, and Qt takes that
directory from `_NSGetExecutablePath`, which still named the host (`App.app/StudPadStudio`). Studio
therefore looked for `App.app/../Resources/AppSettings.xml`, found nothing, and showed "Some Studio
files are missing or corrupted" before it created a window — build 98's log recorded that dialog.
The shim answers `_NSGetExecutablePath` with the guest path it was launched with, so the lookup
lands in `RobloxStudio.app/Contents/Resources`, the bundle the iPad downloads.

The setup screen reports memory entitlement and debugger state. Touch, keyboard and rendering still
need device verification. The shim can host a layer supplied by Qt or Studio, but that does not
implement desktop OpenGL.
To fall back to Qt's offscreen platform (no window, log only), write
`Documents/studpad.plist` with `QtPlatform = offscreen`.

## Layout

| Path | What it does |
|---|---|
| `recon/fetch_studio.sh` | Resolves the Mac Studio build and downloads its official package in CI; the iPad fetches the pinned package's Resources on first run |
| `recon/studio_recon.py` | Mach-O inventory, imports, iOS SDK gap ranking → the Phase 0 report |
| `tools/ios_retarget.py` | Platform/path/shim rewrite, `MH_EXECUTE`→`MH_DYLIB`, duplicate and ordinal handling |
| `tools/plan_shim.py` | Works out which symbols iOS lacks and generates logging stubs + the reroute list |
| `tools/check_binds.py` | Reads every bind from the Mach-O itself; refuses a build the shim cannot satisfy, and lists the frameworks to re-export |
| `shim/MacShim.m` | UIKit-backed `NSApplication`/`NSWindow`/`NSView`/`NSAlert`, drawing and event bridge, `MSStubObject`, guest loader, JIT/memory probe, counted logging |
| `app/starter.m`, `app/Info.plist` | The UIKit host app and its bundle |
| `app/entitlements-sideload.plist` | What the IPA asks for: memory limit, extended addressing, `get-task-allow` |
| `studio/build.sh`, `studio/verify.py` | The pipeline and its packaging check |
| `probe/` | Small app that tests whether SideStore re-signs nested Mach-O images |
| `docs/` | Phase 0 recon and the CyPort write-up |

## Hard rules

- **No Roblox binaries in git, releases or shared artifacts.** CI downloads Studio from Roblox's
  official CDN, and the app downloads the matching package on the device. CI uploads only a private,
  short-retention installer artifact for the user's own run.
- **Interoperability only.** Imports are inspected to learn which APIs a shim must supply. Nothing
  bypasses, patches out or defeats an integrity check or licence protection.
- **Do not guess.** Anything not measured on a runner or a device is marked unverified.
- This repository stays private. Running Studio on an unsupported platform is a policy risk on
  Roblox's side, separate from the technical work.

## Credits

[CyPort](https://github.com/Thijs2004/CyPort) (MIT) for the retarget + shim + sideload-entitlements
architecture, [Slashplayed](https://github.com/paulstraw/slashplayed) (MIT) for the loader and shim
research, and [GetMoreRam](https://github.com/hugeBlack/GetMoreRam) for the free-account memory
entitlement. No third-party code is vendored here.


