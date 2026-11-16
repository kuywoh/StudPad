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
After a Studio view appears, the log panel is hidden so it does not cover the app; tap **Logs** to
open it again. The useful lines include:

```
debugger attached: yes|no
JIT: executable mmap granted|refused (errno …)
memory: 1234 MB available to this process      # current headroom; not the per-app limit
allocator: malloc(64) -> mimalloc heap …       # libsystem_malloc here means Qt and Studio mix heaps
dlopen returned 0x…; images 3 -> 14            # dyld accepted Studio and the Qt dylibs
calling Studio main
[shim] NSWindow(UIWindow) … scene=0x…         # Qt created a window
[stub] … / [miss] -[NSView …]                 # the next API to implement
```

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
| `shim/MacShim.m` | UIKit-backed `NSApplication`/`NSWindow`/`NSView`, drawing and event bridge, `MSStubObject`, guest loader, JIT/memory probe, logging |
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


