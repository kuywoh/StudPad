# StudPad

Private research repo for running the official **macOS arm64 Roblox Studio** build on an
**iPad Air M4 (iPadOS 26)** with a translation layer, following the approach described by
[Slashplayed](https://github.com/paulstraw/slashplayed) (MIT): the Mac app runs unmodified, its
load commands are rewritten to reach shim libraries, and the shims stand in for the macOS
frameworks Studio imports.

**Status: Phase 0 (recon).** There is no device build yet, and this README does not claim one works.

## Hard rules

- **No Roblox binaries in git, releases, or artifacts.** CI downloads Studio from Roblox's
  official CDN inside the macOS runner and uploads **text reports only**. No `.app`, `.dylib`,
  `.zip`, `.dmg`, or extracted resource is committed.
- **Interoperability only.** Imports are inspected to learn which APIs a shim must supply. Do not
  bypass, patch out, or defeat integrity checks, anti-tamper, or license protection. If one blocks
  this approach, stop and report it.
- **Do not guess.** Anything not measured on a runner or device is marked unverified.
- This repository stays private.

## Layout

| Path | What it does |
|---|---|
| `recon/fetch_studio.sh` | Resolves the live Mac Studio build and downloads the official package (runner only) |
| `recon/studio_recon.py` | Mach-O inventory, system-library imports, iOS SDK gap buckets, static protection indicators |
| `.github/workflows/recon-studio.yml` | One-off macOS job; the artifact is text only |
| `docs/phase0.md` | Phase 0 findings (written after the first recon run) |

## Running recon

Actions → **recon-studio** → *Run workflow*. A run takes roughly 8–12 minutes on a standard
macOS runner (about 80–120 billed minutes at the 10× macOS multiplier). The artifact contains
`report.md`, `macho.tsv`, `deps.tsv`, `imports.tsv`, `gap_by_library.tsv`, `gap_missing.tsv`,
`gap_different.tsv`, `protection.txt`, `frameworks.txt`, `gap_summary.json`, and `env.txt`.

The download step refuses a package under 100 MB, because the small `RobloxStudio.zip` on the same
CDN is only the installer; the real app is `version-<hash>-RobloxStudioApp.zip`. The archive under
`mac/` is the **Intel** build; Roblox's installer selects `mac/arm64/` on Apple Silicon, so the
workflow defaults to `mac/arm64/` (input `package_path`).

## Credits

The loader/shim architecture this project evaluates comes from Slashplayed, MIT-licensed:
<https://github.com/paulstraw/slashplayed>. No Slashplayed code is vendored here yet.
