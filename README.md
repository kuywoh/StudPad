# StudPad

Bring-up of the official **arm64 macOS Roblox Studio** on an **iPad Air M4 (iPadOS 26)**, built
entirely in GitHub Actions (no Xcode on your machine) and sideloaded with SideStore.

Studio's Mac build is ordinary arm64 code, so it does not need emulation: it needs iOS dyld to accept
its Mach-O header, a `libMacShim.dylib` for the macOS frameworks it imports, and a UIKit app around
it. That is the same three-part architecture [CyPort](https://github.com/Thijs2004/CyPort) uses to
run a Mac game on iPhone/iPad, and [Slashplayed](https://github.com/paulstraw/slashplayed) uses for a
Mac game client. See [docs/cyport.md](docs/cyport.md).

**Status: bring-up.** The build produces an installable IPA that loads Studio's images and logs where
it stops. It is **not** a working Studio: Qt runs on its offscreen platform because making Qt's Cocoa
platform plugin behave over UIKit is the open problem. [docs/phase0.md](docs/phase0.md) has the
static analysis (2,589 imports, 387 missing) and the feasibility verdict.

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
3. SideStore → My Apps → **+** → `StudPadStudio.ipa`.
4. Optional: [StikDebug](https://github.com/StikDebug/StikDebug) if something needs a debugger. It
   needs `get-task-allow`, which this IPA asks for. Studio does not appear on StikDebug's iOS 26
   supported-app list, and its static imports show no JIT use, so this is untested and probably
   unnecessary.

Then open **StudPad Studio** and read the log (on screen, and in Files → On My iPad → StudPad Studio →
`studio.log`). `[stub]` and `[miss]` lines name the next thing to implement.

## Layout

| Path | What it does |
|---|---|
| `recon/fetch_studio.sh` | Resolves the live Mac Studio build and downloads `mac/arm64/...RobloxStudioApp.zip` (runner only) |
| `recon/studio_recon.py` | Mach-O inventory, imports, iOS SDK gap ranking → the Phase 0 report |
| `tools/ios_retarget.py` | Platform/path/shim rewrite, `MH_EXECUTE`→`MH_DYLIB`, duplicate and ordinal handling |
| `tools/plan_shim.py` | Works out which symbols iOS lacks and generates logging stubs + the reroute list |
| `tools/check_binds.py` | Refuses a build whose shim cannot satisfy every bound import |
| `shim/MacShim.m` | AppKit-over-UIKit slice, `MSStubObject`, guest loader, logging |
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
