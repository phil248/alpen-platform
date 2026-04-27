#!/usr/bin/env python3
"""Alpen Platform plugin customizer (script form).

Substitutes ~~placeholder values in a plugin's markdown + JSON files using
values from a tenant's placeholders.yaml. Designed to be called by the
alpen-plugin-customizer SKILL or invoked directly for batch/CI use.

Usage:
  alpen-customize.py --plugin sales --tenant phil-howard --dry-run
  alpen-customize.py --plugin sales --tenant phil-howard --apply
  alpen-customize.py --plugin sales --tenant phil-howard --apply --commit
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

PLACEHOLDER_RE = re.compile(r"~~([A-Za-z0-9_-]+)")
PLATFORM_ROOT = Path(__file__).resolve().parent.parent


def load_placeholders(tenant_id: str) -> dict[str, str]:
    """Load and flatten placeholders from upstream + alpen_extensions."""
    pack_path = PLATFORM_ROOT / "tenants" / tenant_id / "placeholders.yaml"
    if not pack_path.exists():
        sys.exit(f"error: placeholder pack not found: {pack_path}")
    with pack_path.open() as f:
        data = yaml.safe_load(f)
    flat: dict[str, str] = {}
    for section in ("upstream", "alpen_extensions"):
        for key, value in (data.get(section) or {}).items():
            if value is None or (isinstance(value, str) and value == ""):
                continue
            flat[key] = str(value).rstrip("\n")
    return flat


def find_plugin_files(plugin_dir: Path) -> list[Path]:
    return [
        p for p in plugin_dir.rglob("*")
        if p.is_file() and p.suffix in (".md", ".json")
        and ".git" not in p.parts
    ]


def scan_placeholders(files: list[Path]) -> dict[str, list[tuple[Path, int]]]:
    """Return {placeholder_name: [(file, line_number), ...]}."""
    occurrences: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    for f in files:
        try:
            for lineno, line in enumerate(f.read_text().splitlines(), 1):
                for match in PLACEHOLDER_RE.finditer(line):
                    occurrences[match.group(1)].append((f, lineno))
        except UnicodeDecodeError:
            continue
    return occurrences


def classify(
    occurrences: dict[str, list[tuple[Path, int]]],
    pack: dict[str, str],
) -> tuple[dict, dict, dict]:
    """Split into (prefillable, intentionally_unset, unknown)."""
    pack_keys = set(pack.keys())
    prefillable, unset, unknown = {}, {}, {}
    pack_path = PLATFORM_ROOT / "tenants"
    # Re-read full pack to know which keys exist with empty values vs. missing
    # (we need to distinguish "tenant deliberately blank" from "no entry at all")
    existing_keys: set[str] = set()
    for tenant_dir in pack_path.glob("*/placeholders.yaml"):
        with tenant_dir.open() as f:
            data = yaml.safe_load(f) or {}
        for section in ("upstream", "alpen_extensions"):
            existing_keys.update((data.get(section) or {}).keys())
    for name, locs in occurrences.items():
        if name in pack_keys:
            prefillable[name] = locs
        elif name in existing_keys:
            unset[name] = locs
        else:
            unknown[name] = locs
    return prefillable, unset, unknown


def substitute(
    files: list[Path],
    pack: dict[str, str],
    pack_keys_to_apply: set[str],
    dry_run: bool,
) -> tuple[int, list[tuple[Path, str, str]]]:
    """Return (file_change_count, sample_diffs)."""
    changes = 0
    sample_diffs: list[tuple[Path, str, str]] = []
    for f in files:
        try:
            original = f.read_text()
        except UnicodeDecodeError:
            continue

        def replace(match: re.Match) -> str:
            name = match.group(1)
            if name in pack_keys_to_apply:
                return pack[name]
            return match.group(0)  # leave ~~name in place

        new = PLACEHOLDER_RE.sub(replace, original)
        if new != original:
            changes += 1
            if len(sample_diffs) < 3:
                # capture first changed line as sample
                for o, n in zip(original.splitlines(), new.splitlines()):
                    if o != n:
                        sample_diffs.append((f, o.strip(), n.strip()))
                        break
            if not dry_run:
                f.write_text(new)
    return changes, sample_diffs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", required=True, help="plugin name (dir under platform root)")
    parser.add_argument("--tenant", required=True, help="tenant id (dir under tenants/)")
    parser.add_argument("--dry-run", action="store_true", help="show planned changes; don't write")
    parser.add_argument("--apply", action="store_true", help="apply substitutions")
    parser.add_argument("--commit", action="store_true", help="git commit after apply")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        sys.exit("error: must pass --dry-run or --apply")

    plugin_dir = PLATFORM_ROOT / args.plugin
    if not plugin_dir.is_dir():
        sys.exit(f"error: plugin dir not found: {plugin_dir}")

    pack = load_placeholders(args.tenant)
    files = find_plugin_files(plugin_dir)
    occurrences = scan_placeholders(files)

    if not occurrences:
        print(f"no ~~ placeholders found in {plugin_dir}; nothing to do.")
        return 0

    prefillable, unset, unknown = classify(occurrences, pack)

    # Header
    mode = "DRY RUN" if args.dry_run else "APPLY"
    print(f"=== alpen-customize: {args.plugin} → {args.tenant} [{mode}] ===")
    print(f"placeholder pack:  {len(pack)} keys with values")
    print(f"plugin files:      {len(files)} (.md + .json)")
    print(f"unique placeholders found: {len(occurrences)}")
    print(f"  pre-fillable:    {len(prefillable)}  (have value in pack)")
    print(f"  unset:           {len(unset)}        (in pack, but value blank)")
    print(f"  unknown:         {len(unknown)}      (no entry in pack)")
    print()

    if prefillable:
        print("--- pre-fillable (will substitute) ---")
        for name in sorted(prefillable):
            count = len(prefillable[name])
            value = pack[name]
            short = value if len(value) <= 60 else value[:57] + "..."
            print(f"  ~~{name:<30}  ({count}x) → {short}")
        print()
    if unset:
        print("--- unset (left as ~~ for tenant to decide) ---")
        for name in sorted(unset):
            count = len(unset[name])
            print(f"  ~~{name:<30}  ({count}x) [pack value is empty]")
        print()
    if unknown:
        print("--- unknown (not in pack — manual review needed) ---")
        for name in sorted(unknown):
            count = len(unknown[name])
            sample = unknown[name][0]
            print(f"  ~~{name:<30}  ({count}x) e.g. {sample[0].relative_to(PLATFORM_ROOT)}:{sample[1]}")
        print()

    pack_keys_to_apply = set(prefillable.keys())
    changes, sample_diffs = substitute(files, pack, pack_keys_to_apply, dry_run=args.dry_run)
    verb = "would change" if args.dry_run else "changed"
    print(f"=== {changes} files {verb} ===")

    if sample_diffs:
        print("--- sample diff ---")
        for f, o, n in sample_diffs:
            print(f"  {f.relative_to(PLATFORM_ROOT)}")
            print(f"    -  {o[:100]}")
            print(f"    +  {n[:100]}")

    if args.apply and args.commit and changes:
        rel_plugin = plugin_dir.relative_to(PLATFORM_ROOT)
        msg = f"chore({rel_plugin}): customize for {args.tenant} via alpen placeholders"
        subprocess.run(["git", "add", str(plugin_dir)], cwd=PLATFORM_ROOT, check=True)
        subprocess.run(["git", "commit", "-m", msg], cwd=PLATFORM_ROOT, check=True)
        print(f"committed: {msg}")

    return 0 if changes >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
