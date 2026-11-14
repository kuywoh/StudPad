#!/usr/bin/env python3
"""Phase 0 recon for the official macOS Roblox Studio build.

Usage: python3 recon/studio_recon.py --work .work --out recon-out

Reads the app extracted by recon/fetch_studio.sh and writes text files only:

  report.md            human-readable summary
  env.txt              runner and toolchain facts (written by the workflow)
  macho.tsv            every Mach-O in the bundle: archs, min OS, load-command facts
  deps.tsv             each Mach-O's LC_LOAD_DYLIB dependencies
  imports.tsv          unique (binary, source library, symbol)
  frameworks.txt       bundle layout: frameworks, helpers, largest files
  protection.txt       static indicators for JIT, code checks, spawns, anti-tamper
  gap_by_library.tsv   imports per macOS library, bucketed against the iOS SDK
  gap_missing.tsv      symbols with no iOS SDK provider
  gap_different.tsv    symbols iOS exports from a different library

The iOS side is the iPhoneOS SDK's .tbd index: same approach as Slashplayed's
scripts/recon/bucket.py (MIT), rewritten here to aggregate a whole app bundle.
No binary is copied into the output directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from collections import defaultdict

import yaml

MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe",  # MH_MAGIC_64 (little endian)
    b"\xce\xfa\xed\xfe",  # MH_MAGIC (little endian)
    b"\xca\xfe\xba\xbe",  # FAT_MAGIC (big endian)
    b"\xbe\xba\xfe\xca",  # FAT_CIGAM
}

OBJC_PREFIXES = {
    "_OBJC_CLASS_$_": "objc-class",
    "_OBJC_METACLASS_$_": "objc-metaclass",
    "_OBJC_IVAR_$_": "objc-ivar",
    "_OBJC_EHTYPE_$_": "objc-ehtype",
}

# Imports that change the feasibility analysis. Presence is an indicator, never proof.
PROTECTION_SYMBOLS = {
    "_ptrace": "debugger attach / anti-debug",
    "_csops": "code-signing status query",
    "_SecCodeCheckValidity": "dynamic code-signature validation",
    "_SecCodeCopySelf": "code-signature inspection",
    "_SecStaticCodeCheckValidity": "static code-signature validation",
    "_SecRequirementCreateWithString": "code-signature requirement check",
    "_posix_spawn": "posix_spawn (iOS denies launching bundled executables)",
    "_posix_spawnp": "posix_spawnp",
    "_fork": "fork",
    "_execve": "execve",
    "_pthread_jit_write_protect_np": "W^X JIT toggle (macOS-only API)",
    "_JITWriteSeparateHeaps": "JavaScriptCore JIT heap (macOS-only API)",
    "_vm_protect": "explicit memory protection changes",
    "_mprotect": "explicit memory protection changes",
    "_mmap": "memory mapping",
    "_OBJC_CLASS_$_NSTask": "NSTask subprocess launch",
    "_OBJC_CLASS_$_NSXPCConnection": "XPC service connection",
    "_OBJC_CLASS_$_NSWorkspace": "NSWorkspace (launching other apps)",
}

STRING_INDICATORS = [
    b"hyperion",
    b"byfron",
    b"warden",
    b"vmprotect",
    b"themida",
    b"anti-debug",
    b"antidebug",
    b"tampered",
    b"integrity check",
    b"code signature invalid",
    b"map_jit",
]

BROWSER_NAMES = [
    "chromium embedded framework",
    "libcef",
    "electron framework",
    "qtwebengine",
    "webkit",
    "wkwebview",
]


def run(args, timeout=300):
    """Run a tool; never raise. Returns (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(
            args,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        return p.returncode, p.stdout, p.stderr
    except Exception as exc:  # noqa: BLE001 - recon must keep going
        return 1, "", f"{type(exc).__name__}: {exc}"


def short_name(install_name: str) -> str:
    # Matches dyld_info's "(from X)" naming: AppKit, libSystem, libc++abi, QtCore.
    return os.path.basename(install_name).split(".")[0]


def is_macho(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4) in MACHO_MAGICS
    except OSError:
        return False


def is_system_install(name: str) -> bool:
    return name.startswith(("/usr/lib/", "/System/Library/"))


# --------------------------------------------------------------------------- SDK index


class _TbdLoader(yaml.SafeLoader):
    pass


_TbdLoader.add_multi_constructor(
    "!", lambda loader, suffix, node: loader.construct_mapping(node)
)


def _syms_from_section(entries):
    out = set()
    if isinstance(entries, dict):
        entries = [entries]
    for entry in entries or []:
        out.update(entry.get("symbols") or [])
        out.update(entry.get("weak-symbols") or [])
        out.update(entry.get("thread-local-symbols") or [])
        for cls in entry.get("objc-classes") or []:
            out.add("_OBJC_CLASS_$_" + cls)
            out.add("_OBJC_METACLASS_$_" + cls)
        for cls in entry.get("objc-eh-types") or []:
            out.add("_OBJC_EHTYPE_$_" + cls)
        for cls in entry.get("objc-ivars") or []:
            out.add("_OBJC_IVAR_$_" + cls)
    return out


class TbdIndex:
    """install-name -> exported symbols and re-exported install names for one SDK."""

    def __init__(self, sdk: str, roots, label: str):
        self.label = label
        self.exports = defaultdict(set)
        self.reexports = defaultdict(set)
        files = 0
        for root in roots:
            full = os.path.join(sdk, root)
            for dirpath, dirnames, filenames in os.walk(full):
                dirnames[:] = [
                    d for d in dirnames if d not in ("Headers", "Modules", "PrivateHeaders")
                ]
                for name in filenames:
                    if name.endswith(".tbd"):
                        self._load(os.path.join(dirpath, name))
                        files += 1
        self.files = files

    def _load(self, path):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                docs = list(yaml.load_all(fh, Loader=_TbdLoader))
        except Exception:  # noqa: BLE001 - one odd .tbd must not sink the index
            return
        for doc in docs:
            if not doc or "install-name" not in doc:
                continue
            name = doc["install-name"]
            self.exports[name] |= _syms_from_section(doc.get("exports"))
            self.exports[name] |= _syms_from_section(doc.get("reexports"))
            for entry in doc.get("reexported-libraries") or []:
                self.reexports[name].update(entry.get("libraries") or [])

    def closure(self, name):
        seen, stack = set(), [name]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self.reexports.get(cur, ()))
        return seen

    def provider(self, name, sym):
        for candidate in sorted(self.closure(name)):
            if sym in self.exports.get(candidate, ()):
                return candidate
        return None

    def find_anywhere(self, sym):
        if not hasattr(self, "_by_symbol"):
            self._by_symbol = defaultdict(list)
            for name in sorted(self.exports):
                for symbol in self.exports[name]:
                    self._by_symbol[symbol].append(name)
        return self._by_symbol.get(sym, [])

    def install_name_for(self, short: str):
        if not hasattr(self, "_by_short"):
            self._by_short = {}
            for name in sorted(self.exports, key=len):
                self._by_short.setdefault(short_name(name), name)
        return self._by_short.get(short)


# --------------------------------------------------------------------------- Mach-O facts


def parse_load_commands(text: str):
    cmds = defaultdict(list)
    current = None
    for raw in text.splitlines():
        m = re.match(r"\s*cmd (LC_\w+)\s*$", raw)
        if m:
            current = m.group(1)
            cmds[current].append([])
            continue
        if current is not None:
            cmds[current][-1].append(raw.strip())
    facts = {}
    build = cmds.get("LC_BUILD_VERSION", [[]])[0]
    for line in build:
        if line.startswith("platform "):
            facts["platform"] = line.split()[1]
        elif line.startswith("minos "):
            facts["minos"] = line.split()[1]
        elif line.startswith("sdk "):
            facts["sdk"] = line.split()[1]
    vmin = cmds.get("LC_VERSION_MIN_MACOSX", [[]])[0]
    for line in vmin:
        if line.startswith("version ") and "minos" not in facts:
            facts["minos"] = line.split()[1]
    ident = cmds.get("LC_ID_DYLIB", [[]])[0]
    for line in ident:
        if line.startswith("name "):
            facts["install_name"] = line.split(" ", 1)[1].strip()
    rpaths = []
    for block in cmds.get("LC_RPATH", []):
        for line in block:
            if line.startswith("path "):
                rpaths.append(line.split(" ", 1)[1].split(" (offset")[0])
    facts["rpaths"] = rpaths
    enc = cmds.get("LC_ENCRYPTION_INFO_64", []) or cmds.get("LC_ENCRYPTION_INFO", [])
    if enc:
        for line in enc[0]:
            if line.startswith("cryptid "):
                facts["cryptid"] = line.split()[1]
    facts["lc_main"] = "LC_MAIN" in cmds
    facts["chained_fixups"] = "LC_DYLD_CHAINED_FIXUPS" in cmds
    facts["code_signature"] = "LC_CODE_SIGNATURE" in cmds
    facts["restrict_segment"] = "__RESTRICT" in text
    return facts


def parse_deps(text: str):
    deps = []
    for line in text.splitlines()[1:]:
        line = line.strip()
        if not line or " (compatibility version" not in line:
            continue
        deps.append(line.split(" (compatibility version")[0].strip())
    return deps


def read_entitlements(path: str):
    _, out, err = run(["codesign", "-d", "--entitlements", ":-", path], timeout=60)
    for candidate in (out, err):
        start = candidate.find("<?xml")
        end = candidate.find("</plist>")
        if start >= 0 and end > start:
            try:
                return plistlib.loads(candidate[start : end + 8].encode())
            except Exception:  # noqa: BLE001
                return None
    return None


def read_codesign(path: str):
    _, out, err = run(["codesign", "-dv", "--verbose=4", path], timeout=60)
    text = out + err
    info = {}
    for line in text.splitlines():
        if line.startswith("flags="):
            info["flags"] = line.split("=", 1)[1].strip()
        elif line.startswith("TeamIdentifier="):
            info["team"] = line.split("=", 1)[1].strip()
        elif line.startswith("Authority="):
            info.setdefault("authorities", []).append(line.split("=", 1)[1].strip())
        elif line.startswith("Identifier="):
            info["identifier"] = line.split("=", 1)[1].strip()
    info["hardened"] = "runtime" in info.get("flags", "")
    info["raw_flags"] = info.get("flags", "")
    return info


def collect_machos(app: str):
    found = []
    for dirpath, dirnames, filenames in os.walk(app):
        dirnames[:] = [d for d in dirnames if d != "_CodeSignature"]
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                continue
            if is_macho(path):
                found.append(path)
    return sorted(found)


def scan_strings(path: str, limit=512 * 1024 * 1024):
    counts = {}
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            remaining = min(size, limit)
            carry = b""
            while remaining > 0:
                chunk = fh.read(min(8 * 1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                hay = (carry + chunk).lower()
                for needle in STRING_INDICATORS:
                    counts[needle.decode()] = counts.get(needle.decode(), 0) + hay.count(needle)
                carry = hay[-64:]
    except OSError:
        pass
    return {k: v for k, v in counts.items() if v}


# --------------------------------------------------------------------------- report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=".work")
    ap.add_argument("--out", default="recon-out")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    work = os.path.abspath(args.work)
    out = os.path.abspath(args.out)

    fetch = {}
    fetch_path = os.path.join(work, "fetch.txt")
    if os.path.exists(fetch_path):
        for line in open(fetch_path, encoding="utf-8"):
            if "=" in line:
                k, v = line.rstrip("\n").split("=", 1)
                fetch[k] = v

    app = fetch.get("app") or ""
    if not app or not os.path.isdir(app):
        candidates = []
        root = os.path.join(work, "app")
        for dirpath, dirnames, _ in os.walk(root):
            for d in dirnames:
                if d.endswith(".app"):
                    candidates.append(os.path.join(dirpath, d))
        if not candidates:
            sys.exit(f"no .app found under {root}")
        app = max(candidates, key=lambda p: os.path.getsize(p) if os.path.isdir(p) else 0)

    info_path = os.path.join(app, "Contents", "Info.plist")
    info = {}
    if os.path.exists(info_path):
        try:
            info = plistlib.load(open(info_path, "rb"))
        except Exception:  # noqa: BLE001
            info = {}

    print(f"app: {app}", flush=True)
    machos = collect_machos(app)
    print(f"Mach-O files: {len(machos)}", flush=True)

    macho_rows = []
    dep_rows = []
    import_rows = []
    all_imports = set()
    imports_by_binary = {}
    arch_counter = defaultdict(int)
    errors = []

    for i, path in enumerate(machos, 1):
        rel = os.path.relpath(path, app)
        _, lipo_out, _ = run(["lipo", "-archs", path], timeout=60)
        archs = lipo_out.strip()
        for arch in archs.split():
            arch_counter[arch] += 1
        _, otool_l, _ = run(["otool", "-l", path], timeout=120)
        facts = parse_load_commands(otool_l)
        _, otool_L, _ = run(["otool", "-L", path], timeout=120)
        deps = parse_deps(otool_L)
        for dep in deps:
            dep_rows.append((rel, dep, short_name(dep)))
        _, dyld_out, dyld_err = run(["dyld_info", "-imports", path], timeout=300)
        deps_by_short = {}
        for dep in deps:
            deps_by_short[short_name(dep)] = dep
        pairs = []
        for line in dyld_out.splitlines():
            m = re.match(r"\s+(?:0x[0-9A-Fa-f]+\s+)?(\S+)\s+\(from (\S+)\)", line)
            if not m:
                continue
            sym, src = m.group(1), m.group(2)
            src_install = deps_by_short.get(src, "")
            pairs.append((sym, src, src_install))
            if src_install and is_system_install(src_install):
                all_imports.add((src_install, sym))
        imports_by_binary[rel] = pairs
        import_rows.extend((rel, src, sym) for sym, src, _ in pairs)

        ent = read_entitlements(path)
        ent_keys = sorted(ent.keys()) if isinstance(ent, dict) else []
        cs = read_codesign(path)
        macho_rows.append(
            {
                "path": rel,
                "bytes": os.path.getsize(path),
                "archs": archs,
                "minos": facts.get("minos", ""),
                "sdk": facts.get("sdk", ""),
                "platform": facts.get("platform", ""),
                "lc_main": facts["lc_main"],
                "cryptid": facts.get("cryptid", ""),
                "restrict": facts["restrict_segment"],
                "chained": facts["chained_fixups"],
                "install_name": facts.get("install_name", ""),
                "hardened": cs.get("hardened", False),
                "team": cs.get("team", ""),
                "ent_keys": ",".join(ent_keys),
            }
        )
        if dyld_err and "0 imports" not in dyld_err.lower():
            errors.append(f"{rel}: {dyld_err.strip()[:200]}")
        if i % 25 == 0 or i == len(machos):
            print(f"  scanned {i}/{len(machos)}", flush=True)

    # Mach-O table
    cols = [
        "path", "bytes", "archs", "minos", "sdk", "platform", "lc_main", "cryptid",
        "restrict", "chained", "install_name", "hardened", "team", "ent_keys",
    ]
    with open(os.path.join(out, "macho.tsv"), "w", encoding="utf-8") as fh:
        fh.write("\t".join(cols) + "\n")
        for row in macho_rows:
            fh.write("\t".join(str(row.get(c, "")) for c in cols) + "\n")

    with open(os.path.join(out, "deps.tsv"), "w", encoding="utf-8") as fh:
        fh.write("binary\tdependency\tshort\n")
        for row in dep_rows:
            fh.write("\t".join(row) + "\n")

    with open(os.path.join(out, "imports.tsv"), "w", encoding="utf-8") as fh:
        fh.write("binary\tsource\tsymbol\n")
        for row in import_rows:
            fh.write("\t".join(row) + "\n")

    # iOS SDK gap
    print("indexing iPhoneOS SDK .tbd files...", flush=True)
    _, sdk_path, _ = run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], timeout=60)
    sdk_path = sdk_path.strip()
    if not sdk_path:
        sys.exit("xcrun could not find the iphoneos SDK")
    public = TbdIndex(
        sdk_path, ("System/Library/Frameworks", "usr/lib"), "public"
    )
    private = TbdIndex(
        sdk_path, ("System/Library/PrivateFrameworks",), "private"
    )

    print(f"  public: {public.files} .tbd, private: {private.files} .tbd", flush=True)

    gap_counts = defaultdict(lambda: defaultdict(int))
    missing_rows = []
    different_rows = []
    for install, sym in sorted(all_imports):
        src_short = short_name(install)
        bucket, provider = "missing", ""
        ios_install = public.install_name_for(src_short)
        if ios_install:
            found = public.provider(ios_install, sym)
            if found:
                bucket, provider = "available", found
        if bucket == "missing":
            anywhere = public.find_anywhere(sym)
            if anywhere:
                bucket, provider = "different", anywhere[0]
        if bucket == "missing":
            private_hits = private.find_anywhere(sym)
            if private_hits:
                bucket, provider = "private", private_hits[0]
        gap_counts[src_short][bucket] += 1
        if bucket == "missing":
            missing_rows.append((src_short, sym))
        elif bucket in ("different", "private"):
            different_rows.append((src_short, sym, bucket, provider))

    with open(os.path.join(out, "gap_by_library.tsv"), "w", encoding="utf-8") as fh:
        fh.write("source_library\timports\tavailable\tdifferent\tprivate\tmissing\n")
        for src in sorted(gap_counts):
            row = gap_counts[src]
            fh.write(
                "\t".join(
                    [
                        src,
                        str(sum(row.values())),
                        str(row["available"]),
                        str(row["different"]),
                        str(row["private"]),
                        str(row["missing"]),
                    ]
                )
                + "\n"
            )

    with open(os.path.join(out, "gap_missing.tsv"), "w", encoding="utf-8") as fh:
        fh.write("source_library\tsymbol\n")
        for row in missing_rows:
            fh.write("\t".join(row) + "\n")

    with open(os.path.join(out, "gap_different.tsv"), "w", encoding="utf-8") as fh:
        fh.write("source_library\tsymbol\tbucket\tprovider\n")
        for row in different_rows:
            fh.write("\t".join(row) + "\n")

    # Bundle layout and frameworks
    layout = []
    for sub in ("Frameworks", "PlugIns", "Helpers", "XPCServices", "MacOS", "Resources"):
        full = os.path.join(app, "Contents", sub)
        if os.path.isdir(full):
            layout.append(f"{sub}/: {len(os.listdir(full))} entries")
    frameworks = sorted(
        d for d in os.listdir(os.path.join(app, "Contents", "Frameworks"))
    ) if os.path.isdir(os.path.join(app, "Contents", "Frameworks")) else []
    nested_apps = []
    for dirpath, dirnames, _ in os.walk(app):
        for d in dirnames:
            if d.endswith((".app", ".appex")) and os.path.join(dirpath, d) != app:
                nested_apps.append(os.path.relpath(os.path.join(dirpath, d), app))

    largest = sorted(
        ((os.path.getsize(p), os.path.relpath(p, app)) for p in machos), reverse=True
    )[:20]

    with open(os.path.join(out, "frameworks.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"app: {app}\n")
        for key in ("CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion",
                    "LSMinimumSystemVersion", "DTPlatformName", "DTSDKName"):
            if key in info:
                fh.write(f"{key}: {info[key]}\n")
        fh.write("\nlayout:\n")
        for line in layout:
            fh.write(f"  {line}\n")
        fh.write(f"\nframeworks ({len(frameworks)}):\n")
        for name in frameworks:
            fh.write(f"  {name}\n")
        fh.write(f"\nnested apps/extensions ({len(nested_apps)}):\n")
        for name in nested_apps:
            fh.write(f"  {name}\n")
        fh.write("\nlargest Mach-O files:\n")
        for size, path in largest:
            fh.write(f"  {size:>12}  {path}\n")

    # Protection / behaviour indicators
    symbols_by_name = defaultdict(list)
    for install, sym in all_imports:
        symbols_by_name[sym].append(install)
    hits = []
    for sym, why in PROTECTION_SYMBOLS.items():
        if sym in symbols_by_name:
            hits.append((sym, why, len(symbols_by_name[sym])))
    main_exec = os.path.join(app, "Contents", "MacOS", info.get("CFBundleExecutable", "RobloxStudio"))
    string_hits = scan_strings(main_exec) if os.path.exists(main_exec) else {}
    browser_hits = sorted(
        {
            name
            for name in BROWSER_NAMES
            if any(name in f.lower() for f in frameworks + nested_apps)
        }
    )

    main_row = next((r for r in macho_rows if r["path"] == os.path.relpath(main_exec, app)), None)
    with open(os.path.join(out, "protection.txt"), "w", encoding="utf-8") as fh:
        fh.write("Static indicators only. Presence is not proof of behaviour.\n\n")
        fh.write("main executable:\n")
        if main_row:
            for key in ("path", "bytes", "archs", "minos", "cryptid", "restrict",
                        "chained", "hardened", "team", "ent_keys"):
                fh.write(f"  {key}: {main_row.get(key)}\n")
        else:
            fh.write("  (not found)\n")
        fh.write("\nimports of interest:\n")
        for sym, why, count in hits or [("none", "", 0)]:
            fh.write(f"  {sym}  ({why})  imported by {count} libraries\n")
        fh.write("\nstrings in main executable (counts):\n")
        for needle, count in sorted(string_hits.items()):
            fh.write(f"  {needle}: {count}\n")
        if not string_hits:
            fh.write("  none\n")
        fh.write("\nembedded-browser indicators in bundle names:\n")
        for name in browser_hits or ["  none"]:
            fh.write(f"  {name}\n")

    # Qt version
    qt_version = ""
    for rel in ("QtCore.framework/Versions/A/Resources/Info.plist",
                "QtCore.framework/Resources/Info.plist"):
        path = os.path.join(app, "Contents", "Frameworks", rel)
        if os.path.exists(path):
            try:
                qt_version = plistlib.load(open(path, "rb")).get(
                    "CFBundleShortVersionString", ""
                )
            except Exception:  # noqa: BLE001
                pass
            break
    qt_libs = [f for f in frameworks if f.startswith("Qt")]

    # Summary
    total = sum(sum(v.values()) for v in gap_counts.values())
    totals = defaultdict(int)
    for row in gap_counts.values():
        for bucket, count in row.items():
            totals[bucket] += count
    top_missing = sorted(
        gap_counts.items(), key=lambda kv: kv[1]["missing"], reverse=True
    )[:20]
    top_imports = sorted(gap_counts.items(), key=lambda kv: -sum(kv[1].values()))[:20]

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Roblox Studio macOS recon",
        "",
        f"Generated {now} by `recon/studio_recon.py`. Text-only artifact.",
        "",
        "## Package",
        "",
        f"- Studio version: `{fetch.get('version', 'unknown')}`",
        f"- Upload: `{fetch.get('upload', 'unknown')}`",
        f"- CDN path: `{fetch.get('prefix', 'unknown')}`",
        f"- Official URL: {fetch.get('url', 'unknown')}",
        f"- Package bytes: {fetch.get('bytes', 'unknown')}",
        f"- SHA-256: `{fetch.get('sha256', 'unknown')}`",
        f"- App: `{os.path.basename(app)}`",
        "",
        "## Bundle",
        "",
        f"- Identifier: `{info.get('CFBundleIdentifier', '?')}`",
        f"- Version: `{info.get('CFBundleShortVersionString', '?')}`",
        f"- LSMinimumSystemVersion: `{info.get('LSMinimumSystemVersion', '?')}`",
        f"- Mach-O files: {len(machos)}",
        f"- Architectures: " + ", ".join(f"{a} {n}" for a, n in sorted(arch_counter.items())),
        f"- Qt: `{qt_version or 'not detected'}` ({len(qt_libs)} Qt frameworks)",
        f"- Nested apps/extensions: {len(nested_apps)}",
        f"- Main executable: {main_row['archs'] if main_row else '?'} "
        f"minOS {main_row['minos'] if main_row else '?'} "
        f"chained-fixups {main_row['chained'] if main_row else '?'} "
        f"hardened {main_row['hardened'] if main_row else '?'}",
        "",
        "## Imports against the iPhoneOS SDK",
        "",
        f"- Unique system imports: {total}",
        f"- available (same library or its re-exports): {totals['available']}",
        f"- different (iOS exports it elsewhere): {totals['different']}",
        f"- private-only (PrivateFrameworks): {totals['private']}",
        f"- missing: {totals['missing']}",
        "",
        "### Libraries by import count",
        "",
        "| macOS library | imports | available | different | private | missing |",
        "|---|---|---|---|---|---|",
    ]
    for src, row in top_imports:
        lines.append(
            f"| {src} | {sum(row.values())} | {row['available']} | {row['different']} | "
            f"{row['private']} | {row['missing']} |"
        )
    lines += [
        "",
        "### Libraries by missing imports",
        "",
        "| macOS library | missing | imports |",
        "|---|---|---|",
    ]
    for src, row in top_missing:
        lines.append(f"| {src} | {row['missing']} | {sum(row.values())} |")
    lines += [
        "",
        "## Static protection / platform indicators",
        "",
        f"- Chained fixups on main executable: `{main_row['chained'] if main_row else '?'}`",
        f"- `__RESTRICT` segment: `{main_row['restrict'] if main_row else '?'}`",
        f"- Hardened runtime: `{main_row['hardened'] if main_row else '?'}`",
        f"- Entitlement keys: `{main_row['ent_keys'] if main_row else ''}`",
        "",
        "| import | why it matters |",
        "|---|---|",
    ]
    if hits:
        for sym, why, count in hits:
            lines.append(f"| `{sym}` | {why} (imported by {count}) |")
    else:
        lines.append("| none | — |")
    lines += [
        "",
        "String indicators in the main executable (counts): "
        + (", ".join(f"`{k}`={v}" for k, v in sorted(string_hits.items())) or "none"),
        "",
        "Embedded-browser names in the bundle: " + (", ".join(browser_hits) or "none"),
        "",
        "## Artifact contents",
        "",
        "- `macho.tsv`, `deps.tsv`, `imports.tsv`",
        "- `gap_by_library.tsv`, `gap_missing.tsv`, `gap_different.tsv`",
        "- `frameworks.txt`, `protection.txt`, `env.txt`",
        "",
        "## Limits",
        "",
        "- Static only: no code was executed, and no symbol was resolved on a device.",
        "- Import buckets use the iPhoneOS SDK's `.tbd` exports; a symbol can still differ at runtime.",
        "- Presence of an anti-tamper string or a code-signature import is an indicator, not proof.",
        "",
    ]
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    with open(os.path.join(out, "gap_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "version": fetch.get("version"),
                "uploads": fetch.get("upload"),
                "machos": len(machos),
                "imports": total,
                "buckets": totals,
                "qt": qt_version,
                "errors": errors[:50],
            },
            fh,
            indent=1,
        )

    print(
        f"done: {len(machos)} Mach-O, {total} imports, "
        f"missing {totals['missing']}, private {totals['private']}, "
        f"different {totals['different']}, available {totals['available']}",
        flush=True,
    )
    if errors:
        print(f"{len(errors)} per-binary errors (kept in gap_summary.json)", flush=True)


if __name__ == "__main__":
    main()
