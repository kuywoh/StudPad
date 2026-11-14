# StudPad signing probe

A small iOS app that answers two questions before we build a 1.5 GB Studio IPA:

1. Does SideStore re-sign **nested** Mach-O images inside the IPA?
2. Can the app `dlopen` them and call their symbols on this iPad/iOS?

It contains no Roblox code. The host app embeds:

- `Frameworks/ProbeKit.framework/ProbeKit` — a dylib exporting `probe_framework_answer() == 42`
- `Frameworks/StudioGuest.bundle/StudioGuest` — an `MH_BUNDLE` exporting `probe_bundle_answer() == 43`,
  the same shape a retyped Studio executable will have.

On launch it prints the iOS version, checks each file's `LC_CODE_SIGNATURE` and the kernel's
library-validation verdict, then `dlopen`s it and calls the function. Results appear on screen and in
`Documents/probe.log`.

## Install

1. Download the `StudPadProbe` artifact from the workflow run (it contains `StudPadProbe.ipa`).
2. Open SideStore → **My Apps** → **+** → choose the IPA (or open the IPA in Files and share it to SideStore).
3. Launch **StudPad Probe**.

SideStore will create an App ID and a 7-day profile for `com.kuywoh.studpadprobe`. This uses one of the
three free-team app slots; delete it when done.

## Read the result

The screen shows lines like:

```
Frameworks/ProbeKit.framework/ProbeKit: 32768 bytes
  lv: LC_CODE_SIGNATURE at ..., ... bytes
  lv: F_ADDFILESIGS_RETURN = 0
  lv: F_CHECK_LV = 0
  probe_framework_answer() = 42 (expected 42) PASS
Frameworks/StudioGuest.bundle/StudioGuest: ... bytes
  ...
  probe_bundle_answer() = 43 (expected 43) PASS
```

- **Both PASS** — SideStore signs nested dylibs and bundles; the Studio probe can use the
  `dlopen`/retyped-bundle path with no JIT helper, LocalDevVPN, pairing record, or DDI.
- **Only the framework PASSes** — ship the Studio guest inside a framework-shaped directory.
- **Both FAIL** — nested signing is not happening. We use SideStore's JIT (debugger attach) and load
  Studio with spguest instead, or find another nesting SideStore accepts.

The log survives a crash: **Files → On My iPad → StudPad Probe → probe.log** (file sharing is enabled).
