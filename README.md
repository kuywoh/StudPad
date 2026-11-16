# StudPad

Bring-up of the official **arm64 macOS Roblox Studio** on an **iPad Air M4 (iPadOS 26)**, built
entirely in GitHub Actions (no Xcode on your machine) and sideloaded with SideStore.

Studio's Mac build is ordinary arm64 code, so it does not need emulation: it needs iOS dyld to accept
its Mach-O header, a `libMacShim.dylib` for the macOS frameworks it imports, and a UIKit app around
it. That is the same three-part architecture [CyPort](https://github.com/Thijs2004/CyPort) uses to
run a Mac game on iPhone/iPad, and [Slashplayed](https://github.com/paulstraw/slashplayed) uses for a
Mac game client. See [docs/cyport.md](docs/cyport.md).

**Status: first runnable build.** The pipeline produces a verified, sideloadable IPA: Studio's images
are retargeted, every one of the ~8,200 imports the shim has to satisfy resolves, and the host app
opens a UIKit-backed window into which Qt's own Cocoa platform plugin draws. What is **unverified** is
how far Studio gets on the device: that is what `Documents/studio.log` records on the first launch.
[docs/phase0.md](docs/phase0.md) has the static analysis and the feasibility verdict.

Why the shim is shaped the way it is: on iOS 26 the JIT question and the memory question are separate
from loading, and both are handled the way [Henge](https://github.com/Leviidev/Henge) documents for
iOS 26 — an attached debugger (StikDebug) for executable memory, and `increased-memory-limit` from
GetMoreRam for the per-app limit. Studio's static imports show no JIT use, so JIT is a safety net, not
a requirement. The app logs whether a debugger is attached, whether an RWX mapping is granted, and how
much memory the process actually has.

## Build it

Actions → **studio-build** → *Run workflow* (or push to `shim/`, `app/`, `tools/`, `studio/`).

The job downloads the official arm64 Studio package inside the runner, retargets it, generates the
shim stubs, links, checks every symbol binding, ad-hoc signs with the sideload entitlements, and
uploads `StudPadStudio.ipa`. Text reports (`build.log`, `shim-plan.txt`, `retarget.log`) are uploaded
even when the build fails. Roughly 10–15 minutes on a `macos-15` runner.

## Install it (SideStore, free Apple ID)

1. SideStore installed and refreshing (see <https://docs.sidestore.io/>).
2. [GetMoreRam](https://github.com/hugeBlack/GetMoreRam): sign in with the same Apple ID, pick the
   App ID for `com.kuywoh.studpadstudio`, **Add Increased Memory Limit**. Studio is a desktop IDE with
   a 200 MB executable plus Qt; the default per-app limit is the first wall it hits. Reinstall/refresh
   in SideStore afterwards so the new profile is used.
3. SideStore → My Apps → **+** → `StudPadStudio.ipa`. The `StudPadStudio-ipa` Actions artifact is a
   zip that wraps the IPA — unzip it first. Installing the artifact zip itself fails with
   "Failed to get bundle ID": the installer finds no `Payload/*.app` inside it.
4. Optional, and only if the log says `JIT: executable mmap refused`: install
   [StikDebug](https://github.com/StikDebug/StikDebug), pair it, and assign
   `com.kuywoh.studpadstudio` the `universal.js` script once. On iOS 26 only a debugger that an app's
   script cooperates with can grant executable memory, so launch StudPad Studio *from StikDebug* after
   that. This needs `get-task-allow` in the installed signature, which the IPA asks for and the build
   verifies. Nothing in Studio's static imports uses a JIT, so this is a safety net; the log reports
   `debugger attached: yes` and `JIT: executable mmap granted` when it is working.

Then open **StudPad Studio** and read the log (on screen, and in Files → On My iPad → StudPad Studio →
`studio.log`). The interesting lines, in order:

```
debugger attached: yes|no
JIT: executable mmap granted|refused (errno …)
memory: 1234 MB available to this process      # low means GetMoreRam did not reach the profile
dlopen returned 0x…; images 3 -> 14            # dyld accepted Studio and the Qt dylibs
calling Studio main
[shim] NSWindow(UIWindow) … scene=0x…         # Qt created a window
[stub] … / [miss] -[NSView …]                 # the next API to implement
```

Tapping the Studio window the first time gives it keyboard focus; hardware keyboards send HID
keycodes, mapped to macOS virtual keycodes in the shim. A two-finger pan becomes a scroll wheel
event. To fall back to Qt's offscreen platform (no window, log only), write
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
