# CyPort, and what StudPad takes from it

[CyPort](https://github.com/Thijs2004/CyPort) (MIT) runs the Apple Silicon macOS build of
Cyberpunk 2077 natively on iPhone/iPad: no emulation, no streaming, no jailbreak. It is the closest
working example of the thing StudPad is trying to do, and its three-part architecture is what
`studio/build.sh` copies.

## The idea

An arm64 macOS binary is already arm64 code. iOS runs the same instructions and the same Metal
driver stack. What is missing is macOS *itself*: the header says "macOS" so dyld refuses it; the
frameworks it imports (AppKit, IOKit, Carbon, CoreAudio HAL) do not exist; and the process has no
UIKit app around it, so iOS kills it 20 seconds after launch.

CyPort's three answers:

1. **Retarget** (`tools/ios_retarget.py`). Rewrite the Mach-O header so the iOS dyld will accept the
   image: `LC_BUILD_VERSION` platform macOS → iOS, versioned framework paths → iOS flat paths, and
   macOS-only frameworks → `@rpath/libMacShim.dylib`. A few instruction-level patches for the
   engine's address-space reservations and watchdog. The binary is otherwise unmodified: no
   disassembly, no code rewrite, no anti-tamper anything.
2. **Shim** (`shim/MacShim.m`). A from-scratch implementation of the macOS surface the app uses,
   written on top of UIKit: `NSApplication`/`NSWindow`/`NSView`/`NSEvent` over a `UIWindowScene`,
   plus stubs for IOKit/Carbon/CoreGraphics. The shim also re-exports the iOS frameworks the app
   still needs (Foundation, CoreGraphics, Security, Metal), so a single library satisfies every
   import that used to come from macOS.
3. **Loader.** The shim boots UIKit *first* (the 20 s scene watchdog), then enters the app's
   `main()` from a run-loop timer and calls the `LC_MAIN` entry offset of the mapped image. Because
   Studio's executable is `MH_EXECUTE` and dyld will not `dlopen` that, the build retypes it to
   `MH_DYLIB` (keeping `LC_MAIN`) exactly as LiveContainer does.

Two details from CyPort that are easy to get wrong and are implemented here:

- **Two-level namespace.** A symbol only binds to the library its import record names. Redirecting
  AppKit → shim in the load commands covers every AppKit import, but a symbol that macOS took from
  *UIKitCore* or *libobjc* and iOS does not have must have its import ordinal rewritten to the shim.
  That is what `ios_retarget.py --reroute` does, per bind opcode, and what
  `tools/check_binds.py` verifies before an IPA is produced.
- **Duplicate load commands.** Eight macOS frameworks map to the same shim path. Without collapsing
  the duplicates and renumbering the import ordinals, every bind after the first duplicate reaches
  the wrong library — CyPort's "Symbol not found: _AUGraphAddNode … Expected in: CoreHaptics".

## What is different for Studio

| | CyPort | StudPad |
|---|---|---|
| App | game engine, one big GL/Metal surface | Qt 5.15 Widgets IDE: `libqcocoa.dylib` + 199 AppKit imports |
| Input | virtual gamepad, touch-as-mouse | full desktop text input, menus, docking, file dialogs |
| Own code execution | engine rewrites its own `__TEXT` → needs a debugger-assisted JIT helper | no `MAP_JIT`, no JSC, Luau is interpreted → **no JIT helper needed** |
| Memory | 5 GB, pools of 16/64/32 GB | 200 MB executable + Qt, desktop IDE footprint |

The decisive unknown is unchanged from Phase 0: **Qt's Cocoa platform plugin over a UIKit-backed
AppKit**. CyPort shims AppKit for one game window; Qt's QPA plugin expects a real `NSApplication`
event loop, native menus, panels, tracking areas and text input contexts. The alternative — building
Qt's iOS `qios` plugin against Studio's exact Qt 5.15 build — needs Qt sources matching that ABI and
is its own project.

So the build does not pretend to have a desktop UI yet. It forces Qt's **offscreen** platform and
the **Fusion** style, which lets Qt Widgets construct and layout without a window server, and logs
where Studio stops. That answers the questions that decide the next phase:

- Does dyld accept the retargeted Studio and all nine Qt frameworks, with the shim satisfying every
  AppKit/Carbon import? (`check_binds.py` proves the linking on the runner; only the device proves
  dyld agrees.)
- Does Studio reach its own `main`, spawn a helper process, touch WebKit, or create an
  `NSOpenGLContext` before the first window?
- Which stub is called first? Each one logs, so the log names the AppKit method or C function to
  implement next.

## Install (no Xcode, no Mac)

1. GitHub → **Actions → studio-build → Run workflow** (or push to `shim/`, `app/`, `tools/`,
   `studio/`). Download the `StudPadStudio-ipa` artifact from the run.
2. iPad: install [SideStore](https://docs.sidestore.io/) once (it needs a computer for the initial
   pair, after that it refreshes itself over LocalDevVPN).
3. **GetMoreRam** (<https://github.com/hugeBlack/GetMoreRam>): sign in with the same Apple ID, find
   the App ID for `com.kuywoh.studpadstudio`, *Add Increased Memory Limit*. A free Apple ID cannot
   turn this on any other way, and a desktop IDE will hit the default per-app limit immediately.
   Extended virtual addressing is paid-account only; nothing in the shim depends on it yet.
4. SideStore → **My Apps → +** → pick `StudPadStudio.ipa`. First install creates the App ID; the
   IPA's ad-hoc signature lists `increased-memory-limit`, `extended-virtual-addressing` and
   `get-task-allow`, so SideStore signs with whichever of those the App ID now has. If the memory
   limit was added after the first install, **refresh/reinstall once** so the new profile is used.
5. Optional, only if something needs a debugger: install
   [StikDebug](https://github.com/StikDebug/StikDebug), pair it, and launch StudPad Studio from
   StikDebug. It needs `get-task-allow` in the installed signature (this build asks for it). Studio
   does not appear on StikDebug's iOS 26 supported-app list, so treat JIT as untested and probably
   unnecessary: nothing in Studio's static imports wants executable memory.

## Reading the result

`Documents/studio.log` is the whole point of this build. Files → On My iPad → StudPad Studio →
`studio.log` (the app also shows it on screen, bottom half).

Useful lines:

```
=== StudPad Studio shim ===                 the shim got the main thread
dlopen returned 0x…; images 3 -> 14         dyld accepted Studio and the Qt dylibs
  image 4: …/Frameworks/libQtCore.dylib     the nine Qt frameworks loaded
calling Studio main                          Studio's entry point was reached
[stub] NSApplicationMain()                   a symbol we only stubbed was called
[miss] -[NSWindow setDelegate:]              an AppKit method the shim does not implement
```

A signal plus backtrace at the end means a stub was called for something that needs a real
implementation; the frame above it names the subsystem.

## Rules this project keeps

- Studio is downloaded from Roblox's official CDN inside the CI job. No Roblox binary is committed,
  released or redistributed; the IPA is a private artifact for the device that built it.
- Interoperability only: imports are inspected to learn which APIs a shim must supply. Nothing
  bypasses, patches out or defeats an integrity check, and nothing here is a licence circumvention.
- Running Studio on an unsupported platform is a policy risk on Roblox's side, separate from the
  technical work. That risk is the user's to accept.

Slashplayed (<https://github.com/paulstraw/slashplayed>, MIT) is the other reference: its `spguest`
loader is the manual map/rebase/bind/ObjC-register/call-`LC_MAIN` path, and its notes on why a
debugger is needed for self-modifying code are what told us Studio probably does not need one.
