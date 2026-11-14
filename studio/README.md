# Studio load probe

This is **not** a working Studio. It answers whether iPadOS dyld can load the official arm64 Studio
executable and its nine Qt 5.15 frameworks at all, with every macOS-only import marked weak.

The build:

1. fetches the official arm64 package from Roblox's CDN in the CI job;
2. retypes `Contents/MacOS/RobloxStudio` from `MH_EXECUTE` to `MH_BUNDLE`;
3. maps versioned macOS framework paths to their iOS equivalents;
4. marks AppKit, ApplicationServices, Carbon, ForceFeedback, DiskArbitration, OpenGL, ColorSync,
   Cocoa, and libcups as weak libraries;
5. marks every dyld-info import weak, so a symbol iOS lacks binds to `NULL` instead of failing the load;
6. sets `LC_BUILD_VERSION` to iOS with `vtool`;
7. forces Qt's **offscreen** platform and **Fusion** style, avoiding Cocoa/AppKit for this first probe;
8. loads the guest with `dlopen(RTLD_NOW|RTLD_GLOBAL)`, finds its `LC_MAIN`, and calls the entry.

The host is a normal UIKit app, so the 20-second scene watchdog is satisfied. `stderr` and `stdout` are
redirected to `Documents/studio.log` before the load, and signals write a backtrace there.

## What a useful result looks like

- `dlopen returned ...` and a list of new images means dyld accepted the retyped macOS executable and
  its Qt dylibs. This is the main mechanical unknown.
- `calling Studio entry...` means the guest reached its entry point.
- A signal plus backtrace means a weak import was actually called; the frame and the last log lines
  identify which subsystem to implement next.

## Limits

- Weak imports are `NULL`; any missing function that Qt calls will crash. That is expected and is the
  point of the probe.
- Offscreen Qt does not create a window. A visible Studio UI still needs either an AppKit-over-UIKit
  layer or a Qt iOS platform plugin.
- Studio's resources are copied to the app root; path assumptions are unverified.
- No binary is committed. The IPA exists only as a private workflow artifact.
