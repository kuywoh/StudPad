# The StudPad build

`build.sh` turns the official arm64 macOS Studio package into a sideloadable iOS app. It runs on a
macOS runner (GitHub Actions) or any Mac with the Xcode command line tools; no Apple developer
account is needed because the IPA is ad-hoc signed and SideStore re-signs it on the iPad.

```
studio/build.sh all        # fetch, stage, retarget, plan, link, host, check, sign, package
studio/build.sh <stage>    # one stage; the CI job runs them as separate steps
```

| Stage | What it does |
|---|---|
| `fetch` | Downloads `mac/arm64/<upload>-RobloxStudioApp.zip` from Roblox's CDN (refuses the installer stub) |
| `stage` | Copies `RobloxStudio`, the Qt frameworks as flat dylibs, the helper dylibs and the Qt plugins |
| `retarget1` | Rewrites each Mach-O for iOS dyld: platform, framework paths, `MH_EXECUTE`→`MH_DYLIB`, duplicate load commands and their import ordinals, `libMacShim` redirects. Also records the iOS frameworks to re-export |
| `plan` | Compiles the hand-written shim to learn what it exports, then generates a stub for every symbol the shim must supply that it lacks |
| `retarget2` | Points those symbols' imports at the shim, then **plans again**: rerouting shares ordinal opcodes with neighbouring imports, so the final ordinals decide what the shim must export |
| `link` | Compiles the shim sources and links `libMacShim.dylib`, re-exporting the iOS frameworks the images link |
| `host` | Builds the UIKit host (`app/starter.m`) and fills in its Info.plist |
| `check` | Reads every bind from the Mach-O itself and refuses the build if the shim cannot satisfy one |
| `sign` | Ad-hoc signs every image; the main executable carries `app/entitlements-sideload.plist` |
| `package` | Zips `Payload/` and runs `verify.py` on the result |

## Signing and entitlements

SideStore reads the entitlements it may request from the IPA's **main executable**, not from the
bundle. The build signs that executable outside the bundle (codesign seals the enclosing bundle when
it signs a file inside one and then rejects Studio's copied resources as unsigned nested code), moves
it back, and fails the stage unless `get-task-allow` is really in the signature.

The entitlements requested are `get-task-allow` (StikDebug can attach), `increased-memory-limit` (a
free Apple ID gets this through GetMoreRam on the App ID) and `extended-virtual-addressing` (paid
accounts only; nothing depends on it).

## What the build does not do

- It does not test the result. `verify.py` proves the packaging, retargeting and linking; what Studio
  does is only visible in `Documents/studio.log` on the device.
- It does not implement all of AppKit. Anything the generated stubs answer logs `[stub]` or `[miss]`
  with the symbol or selector name, which is exactly the list for the next iteration.
