# StudPad

Bring-up of the official **arm64 macOS Roblox Studio** on an **iPad Air M4 (iPadOS 26)**, built
entirely in GitHub Actions (no Xcode on your machine) and sideloaded with SideStore.

Studio's Mac build is ordinary arm64 code, so it does not need emulation: it needs iOS dyld to accept
its Mach-O header, a `libMacShim.dylib` for the macOS frameworks it imports, and a UIKit app around
it. That is the same three-part architecture [CyPort](https://github.com/Thijs2004/CyPort) uses to
run a Mac game on iPhone/iPad, and [Slashplayed](https://github.com/paulstraw/slashplayed) uses for a
Mac game client. See [docs/cyport.md](docs/cyport.md).

**Status: CI produces a structurally verified IPA; iPad runtime behavior is unverified.** The build
retargets Studio's images, resolves the imports checked by CI, and packages a UIKit host. The check
does not prove that Studio starts, that its viewport renders, or that every input path works on an
iPad. The desktop `NSOpenGLContext` remains a logged stub. Read `Documents/studio.log` after a device
launch before treating the app as usable.
[docs/phase0.md](docs/phase0.md) has the static analysis and the feasibility verdict.

JIT and memory are separate from loading. The IPA requests `get-task-allow`,
`increased-memory-limit`, and `extended-virtual-addressing`; SideStore can keep only capabilities
allowed by the installed profile. Studio's static imports show no JIT use, so StikDebug is an optional
diagnostic path. The app logs debugger state, the result of an executable-memory probe, and current
memory headroom. That headroom is a momentary reading, not the configured per-app limit or proof that
GetMoreRam was applied.

## Build it

Actions → **studio-build** → *Run workflow* (or push to `shim/`, `app/`, `tools/`, `studio/`).

The job downloads the official arm64 Studio package inside the runner, retargets it, generates the
shim stubs, links, checks every symbol binding, ad-hoc signs with the sideload entitlements, and
uploads `StudPadStudio.ipa`. Text reports (`build.log`, `shim-plan.txt`, `retarget.log`) are uploaded
even when the build fails. Roughly 10–15 minutes on a `macos-15` runner.

## Install it (SideStore, free Apple ID)

1. SideStore installed and refreshing (see <https://docs.sidestore.io/>).
2. If memory pressure stops the app, use [GetMoreRam](https://github.com/hugeBlack/GetMoreRam) with
   the same Apple ID, choose `com.kuywoh.studpadstudio`, and select **Add Increased Memory Limit**.
   Refresh or reinstall in SideStore so it uses the updated profile.
3. SideStore → My Apps → **+** → `StudPadStudio.ipa`. The `StudPadStudio-ipa` Actions artifact is a
   zip that wraps the IPA — unzip it first. Installing the artifact zip itself fails with
   "Failed to get bundle ID": the installer finds no `Payload/*.app` inside it.
4. Optional, and only if a real runtime failure points to executable memory: install
   [StikDebug](https://github.com/StikDebug/StikDebug), pair it, and assign
   `com.kuywoh.studpadstudio` the `universal.js` script once. On iOS 26 only a debugger that an app's
   script cooperates with can grant executable memory, so launch StudPad Studio *from StikDebug* after
   that. The build checks that the IPA requests `get-task-allow`; this does not prove StikDebug works
   with Studio on the installed iOS version. Studio has no known JIT imports, so treat this as
   unverified unless a device failure demonstrates it is needed.

Open **StudPad Studio** and read the log in Files → On My iPad → StudPad Studio → `studio.log`.
After a Studio view appears, the log panel is hidden so it does not cover the app; tap **Logs** to
open it again. The useful lines include:

```
debugger attached: yes|no
JIT: executable mmap granted|refused (errno …)
memory: 1234 MB available to this process      # current headroom; not the per-app limit
dlopen returned 0x…; images 3 -> 14            # dyld accepted Studio and the Qt dylibs
calling Studio main
[shim] NSWindow(UIWindow) … scene=0x…         # Qt created a window
[stub] … / [miss] -[NSView …]                 # the next API to implement
```

The shim maps taps and drags to mouse events, two-finger pans to scrolling, and iPad pointer hover to
mouse movement. Hardware key usages, including modifier transitions, are translated to macOS key
events. The on-screen keyboard and the full Qt editing workflow still need device verification.
The shim can host a layer supplied by Qt or Studio, but that does not implement desktop OpenGL.
To fall back to Qt's offscreen platform (no window, log only), write
`Documents/studpad.plist` with `QtPlatform = offscreen`.

## Layout

| Path | What it does |
|---|---|
| `recon/fetch_studio.sh` | Resolves the live Mac Studio build and downloads `mac/arm64/...RobloxStudioApp.zip` (runner only) |
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
  official CDN and uploads an IPA only as a private, short-retention artifact of the user's own run.
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


