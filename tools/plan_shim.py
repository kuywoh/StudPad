#!/usr/bin/env python3
"""Work out which symbols Studio needs that iOS cannot supply, and write stubs for them.

Every macOS framework Studio imports is either remapped to an iOS framework or redirected to
libMacShim.dylib by tools/ios_retarget.py. Redirecting is not enough on its own: with a two-level
namespace a bind resolves only against the library its import record names, so:

  * a symbol bound to libMacShim.dylib must be exported *by the shim* — which means the shim's own
    code plus the frameworks it re-exports. iOS having the symbol in some other library (say
    UIKitCore) does not help, and this is exactly the AppKit trap: `NSColor` exists on iOS but not
    in anything the shim re-exports.
  * a symbol bound to an iOS library must be exported by the SDK at all. If it is not (AppKit-era
    leftovers like `CGDisplayBounds`, `glClearDepth`), it needs a stub *and* its import ordinal
    rewritten to the shim.

Outputs:

    stubs.c        a C function per C symbol returning 0, logging the first time it is called
    stubs_objc.m   an ObjC class per missing `_OBJC_CLASS_$_X`, inheriting MSStubObject
    stubs_asm.s    symbols whose names are not C identifiers, plus ObjC ivar/eh-type storage
    reroute.txt    the symbols whose imports must move to the shim

TBD parsing note: `.tbd` files do not spell ObjC classes as `_OBJC_CLASS_$_X`. They use
`objc-classes:` (and `objc-ivars:`, `objc-eh-types:`) sections holding the bare names. Missing that
made every class iOS really has look absent, so the generated file redeclared `NSObject`, `NSArray`,
`CALayer` and friends — a build break, and had it linked it would have bound real UIKit classes to
empty stubs.

Known limit: the stub list has no type information, so a stub for a *constant* (`NSFooMode`) is a
function, not a valid object, and a stub for a float- or struct-returning function returns 0 in the
integer register. A crash there is the expected way to find out which symbol needs a real
implementation; the log names it.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_binds import binds, exports, tbd_symbols  # noqa: E402  (same tool directory)

# Clang refuses to redeclare these, and they are compiler builtins no image should bind by name.
SKIP_STUBS = re.compile(r"^__(atomic|builtin)")

# Clang builtins that are harmless to shadow still warn; not worth special-casing.

C_IDENT = re.compile(r"^_([A-Za-z_][A-Za-z0-9_]*)$")
OBJC_CLASS = re.compile(r"^_OBJC_CLASS_\$_([A-Za-z_][A-Za-z0-9_]*)$")
OBJC_META = re.compile(r"^_OBJC_METACLASS_\$_([A-Za-z_][A-Za-z0-9_]*)$")
OBJC_IVAR = re.compile(r"^_OBJC_IVAR_\$_([A-Za-z_][A-Za-z0-9_.]*)$")
OBJC_EHTYPE = re.compile(r"^_OBJC_EHTYPE_\$_([A-Za-z_][A-Za-z0-9_.]*)$")

SHIM_NAME = "libMacShim.dylib"

# Must match the -Wl,-reexport_framework list in studio/build.sh.
REEXPORTS = [
    "Foundation",
    "UIKit",
    "CoreFoundation",
    "CoreGraphics",
    "QuartzCore",
    "CoreText",
    "ImageIO",
    "Security",
    "Metal",
    "GameController",
    "UniformTypeIdentifiers",
    "AudioToolbox",
]

# Classes that must never be replaced by a stub, whatever the SDK scan says: objc itself, the shim's
# own root class, and NSObject are load-bearing for every other class.
NEVER_STUB_CLASSES = {"NSObject", "NSProxy", "MSStubObject"}


def sdk_symbols(sdk: str) -> set[str]:
    """Every external symbol name the iOS SDK's text-based stubs export."""
    found: set[str] = set()
    count = 0
    for root, _dirs, files in os.walk(sdk):
        for name in files:
            if not name.endswith(".tbd"):
                continue
            try:
                with open(os.path.join(root, name), "r", encoding="utf-8", errors="replace") as f:
                    found |= tbd_symbols(f.read())
            except OSError:
                continue
            count += 1
    print(f"  read {count} .tbd files from the SDK ({len(found)} symbols)")
    return found


def framework_symbols(sdk: str, names: list[str]) -> set[str]:
    found: set[str] = set()
    missing = []
    for name in names:
        path = os.path.join(sdk, "System/Library/Frameworks", f"{name}.framework", f"{name}.tbd")
        if not os.path.exists(path):
            missing.append(name)
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            found |= tbd_symbols(f.read())
    if missing:
        print(f"  warning: no .tbd for re-exported {', '.join(missing)}")
    print(f"  re-exported frameworks provide {len(found)} symbols")
    return found


def classify(symbols: list[str]) -> dict[str, list[str]]:
    groups = {"functions": [], "classes": [], "ivars": [], "ehtypes": [], "asm": []}
    for sym in symbols:
        if OBJC_CLASS.match(sym):
            groups["classes"].append(sym)
        elif OBJC_IVAR.match(sym):
            groups["ivars"].append(sym)
        elif OBJC_EHTYPE.match(sym):
            groups["ehtypes"].append(sym)
        elif C_IDENT.match(sym) and not SKIP_STUBS.match(sym):
            groups["functions"].append(sym)
        elif not OBJC_META.match(sym) and not SKIP_STUBS.match(sym):
            groups["asm"].append(sym)
    return groups


def write_c_stubs(groups: dict[str, list[str]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("// Generated by tools/plan_shim.py: iOS does not export these, so the shim does.\n")
        f.write("// Each one returns 0 and logs once. Replace the ones Studio actually needs.\n")
        f.write('#include "MacShim.h"\n\n')
        for sym in sorted(groups["functions"]):
            f.write(f'void *{sym[1:]}(void) {{ return studpad_stub("{sym[1:]}"); }}\n')
        for sym in sorted(groups["classes"]):
            f.write(f"// {sym}: generated as an ObjC class in stubs_objc.m\n")
        for sym in sorted(groups["ivars"]):
            f.write(f"// {sym}: zeroed data in stubs_asm.s\n")
        for sym in sorted(groups["ehtypes"]):
            f.write(f"// {sym}: zeroed data in stubs_asm.s\n")
        for sym in sorted(groups["asm"]):
            f.write(f"// {sym}: not a C identifier, aliased in stubs_asm.s\n")

    asm_path = os.path.splitext(path)[0] + "_asm.s"
    entries = groups["asm"] + groups["ivars"] + groups["ehtypes"]
    if entries:
        with open(asm_path, "w", encoding="utf-8") as f:
            f.write("// Generated by tools/plan_shim.py: symbols whose names are not C identifiers,\n")
            f.write("// and ObjC ivar / exception-type storage (zeroed, 8-byte aligned).\n")
            f.write(".text\n")
            for sym in sorted(groups["asm"]):
                f.write(f".globl {sym}\n{sym} = _studpad_stub_asm\n")
            if groups["ivars"] or groups["ehtypes"]:
                f.write(".data\n.p2align 3\n")
                for sym in sorted(groups["ivars"] + groups["ehtypes"]):
                    f.write(f".globl {sym}\n{sym}:\n\t.zero 64\n")
    elif os.path.exists(asm_path):
        os.remove(asm_path)


def write_objc_stubs(groups: dict[str, list[str]], path: str) -> int:
    names = sorted(
        {
            m.group(1)
            for sym in groups["classes"]
            if (m := OBJC_CLASS.match(sym)) and m.group(1) not in NEVER_STUB_CLASSES
        }
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("// Generated by tools/plan_shim.py: AppKit/Carbon classes iOS does not have.\n")
        f.write("// Each is a real ObjC class so classrefs bind, and logs unknown methods.\n")
        f.write("// Only <objc/NSObject.h> is imported, not Foundation/UIKit: an AppKit class name\n")
        f.write("// that a UIKit header already declares would otherwise be a redeclaration error.\n")
        f.write("#import <objc/NSObject.h>\n\n")
        f.write("// MSStubObject is implemented in shim/MacShim.m; this is only its declaration.\n")
        f.write("@interface MSStubObject : NSObject\n@end\n\n")
        for name in names:
            f.write(f"@interface {name} : MSStubObject\n@end\n")
            f.write(f"@implementation {name}\n@end\n\n")
    return len(names)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdk", required=True)
    ap.add_argument("--guest", required=True)
    ap.add_argument("--shipped", nargs="*", default=[])
    ap.add_argument("--have-object", nargs="*", default=[])
    ap.add_argument(
        "--reexport",
        nargs="*",
        default=[],
        help="iOS frameworks libMacShim re-exports (in addition to REEXPORTS)",
    )
    ap.add_argument("--stubs", required=True)
    ap.add_argument("--objc", required=True)
    ap.add_argument("--reroute", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    images = [args.guest] + list(args.shipped)
    own_exports: set[str] = set()
    for path in args.have_object:
        own_exports |= exports(path)
    ios_all = sdk_symbols(args.sdk)
    reexports = sorted(set(REEXPORTS) | set(args.reexport))
    ios_reexported = framework_symbols(args.sdk, reexports)

    shim_bound: set[str] = set()
    device_bound: set[str] = set()
    attributed = True
    for path in images:
        pairs = binds(path)
        if pairs is None:
            attributed = False
            break
        for symbol, library in pairs:
            if os.path.basename(library) == SHIM_NAME:
                shim_bound.add(symbol)
            else:
                device_bound.add(symbol)

    if not attributed:
        # The fallback cannot tell a Qt-to-Qt import from an AppKit one, and rerouting those would
        # bind studio's own classes to the shim. Refuse instead of producing a broken IPA.
        print("  ERROR: no usable bind information for these images", file=sys.stderr)
        return 1

    print(
        f"  {len(shim_bound)} symbols are bound to the shim, "
        f"{len(device_bound)} to iOS libraries"
    )

    # A symbol the shim must supply: bound to it and not exported by the shim's code, its re-exported
    # frameworks, or anything it links. `--shipped` is not part of this: another dylib exporting a
    # name does not make the shim export it, because binds are resolved against the named library.
    shim_have = own_exports | ios_reexported
    stubs_shim = {s for s in shim_bound if s not in shim_have}
    stubs_device = {s for s in device_bound if s not in ios_all and s not in shim_have}

    # NSObject and NSProxy come from libobjc and are present on every iOS process. Never reroute
    # them: a reroute would make them the shim's problem, and no stub can be the real class.
    def never_stub(sym: str) -> bool:
        m = OBJC_CLASS.match(sym) or OBJC_META.match(sym)
        return bool(m) and m.group(1) in NEVER_STUB_CLASSES

    stubbing = {s for s in (stubs_shim | stubs_device) if not never_stub(s)}
    generated = {m.group(1) for s in stubbing if (m := OBJC_CLASS.match(s))}
    stubs = sorted(
        s
        for s in stubbing
        if not ((m := OBJC_META.match(s)) and m.group(1) in generated)
        if not (m := OBJC_CLASS.match(s)) or m.group(1) not in NEVER_STUB_CLASSES
        if not SKIP_STUBS.match(s)
    )
    if not stubs:
        raise SystemExit("no missing symbols: has Studio changed shape?")

    groups = classify(stubs)
    write_c_stubs(groups, args.stubs)
    classes = write_objc_stubs(groups, args.objc)
    with open(args.reroute, "w", encoding="utf-8") as f:
        f.write("# symbols bound to libMacShim.dylib instead of the library macOS named\n")
        for sym in stubs:
            f.write(sym + "\n")
    with open(args.report, "w", encoding="utf-8") as f:
        f.write("# shim plan\n\n")
        f.write(f"bound to the shim: {len(shim_bound)}\n")
        f.write(f"bound to iOS libraries: {len(device_bound)}\n")
        f.write(f"missing via the shim: {len(stubs_shim)}\n")
        f.write(f"missing from the iOS SDK: {len(stubs_device)}\n")
        f.write(
            f"stubs: {len(stubs)} ({len(groups['functions'])} functions, "
            f"{len(groups['asm'])} aliased, {classes} classes, "
            f"{len(groups['ivars']) + len(groups['ehtypes'])} data)\n\n"
        )
        for sym in stubs:
            f.write(sym + "\n")

    print(
        f"  {len(stubs)} stubs ({len(groups['functions'])} functions, "
        f"{len(groups['asm'])} aliased, {classes} classes, "
        f"{len(groups['ivars']) + len(groups['ehtypes'])} data): "
        f"{len(stubs_shim)} the shim must export, {len(stubs_device)} iOS lacks"
    )
    print("  first: " + ", ".join(s[1:] for s in stubs[:6]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
