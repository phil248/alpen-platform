#!/usr/bin/env python3
"""Inventory MCP refresh-token age. Surfaces rotation candidates.

OAuth refresh tokens are effectively long-lived: once issued, they remain
valid until manually revoked. This is convenient and exactly the wrong
security posture. This script walks ~/Winnie/mcp-servers/<server>/tokens/
and any ~/.claude.json apiKey entries, computes age (using file birth time
as a proxy for issuance), and classifies each into a tier.

Output: $VAULT/HFO/OPSEC/Audits/YYYY-MM-DD-mcp-token-age.md
        (or stdout via --dry-run)

This is the v0.1 of `mcp-key-rotator` — inventory only, no automated
rotation. Most providers don't expose programmatic rotation; v0.2 will
add interactive walkthroughs per provider.

Tier thresholds:
  0-30 days   green    fresh
  30-90       yellow   rotate this quarter
  90-180      orange   rotate now
  180+        red      long overdue

Usage:
  mcp-token-age.py --tenant phil-howard
  mcp-token-age.py --tenant phil-howard --dry-run
  mcp-token-age.py --tenant phil-howard --threshold-days 60
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "bin"))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_NAME = "mcp-token-age"

WINNIE = Path.home() / "Winnie"
MCP_SERVERS_DIR = WINNIE / "mcp-servers"
CLAUDE_CONFIG = Path.home() / ".claude.json"


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def vault_path(tenant_cfg: dict) -> Path:
    raw = tenant_cfg.get("tenant", {}).get("vault_path") or os.environ.get("VAULT_PATH")
    if not raw:
        sys.exit("error: tenant.vault_path not set and VAULT_PATH not in env")
    return Path(os.path.expanduser(raw))


@dataclass
class TokenRecord:
    server: str
    label: str        # account/identifier within server
    path: Path
    age_days: int
    has_refresh: bool
    scopes: list[str]
    tier: str         # green | yellow | orange | red
    notes: str        # extra context for the report


def classify_age(age_days: int) -> str:
    if age_days < 30:
        return "green"
    if age_days < 90:
        return "yellow"
    if age_days < 180:
        return "orange"
    return "red"


def file_birth_age_days(path: Path) -> int:
    """Return days since file birth time. Falls back to mtime on systems
    without st_birthtime (Linux). macOS HFS/APFS supports birthtime."""
    st = path.stat()
    bt = getattr(st, "st_birthtime", st.st_mtime)
    return int((time.time() - bt) // 86400)


def scan_google_workspace_tokens() -> list[TokenRecord]:
    """The bespoke google-workspace MCP server stores per-account tokens
    at ~/Winnie/mcp-servers/google-workspace/tokens/<account>.json."""
    tdir = MCP_SERVERS_DIR / "google-workspace" / "tokens"
    if not tdir.is_dir():
        return []
    out: list[TokenRecord] = []
    for path in sorted(tdir.glob("*.json")):
        # Skip backups / pre-migration artifacts
        if any(s in path.name for s in (".bak-", ".pre-", ".prev")):
            continue
        try:
            with path.open() as f:
                data = json.load(f)
        except Exception:
            continue
        age = file_birth_age_days(path)
        scopes = data.get("scopes") or []
        notes = ""
        if "gmail.send" in " ".join(scopes):
            notes = "send-capable; rotation requires re-OAuth"
        out.append(TokenRecord(
            server="google-workspace",
            label=data.get("account") or path.stem,
            path=path,
            age_days=age,
            has_refresh=bool(data.get("refresh_token")),
            scopes=scopes,
            tier=classify_age(age),
            notes=notes,
        ))
    return out


def scan_other_mcp_tokens() -> list[TokenRecord]:
    """Walk other ~/Winnie/mcp-servers/*/tokens/ folders for non-google MCPs."""
    out: list[TokenRecord] = []
    if not MCP_SERVERS_DIR.is_dir():
        return out
    for srv_dir in sorted(p for p in MCP_SERVERS_DIR.iterdir() if p.is_dir()):
        if srv_dir.name == "google-workspace":
            continue  # handled by dedicated scanner
        tdir = srv_dir / "tokens"
        if not tdir.is_dir():
            continue
        for path in sorted(tdir.glob("*.json")):
            if any(s in path.name for s in (".bak-", ".pre-", ".prev")):
                continue
            try:
                with path.open() as f:
                    data = json.load(f)
            except Exception:
                continue
            age = file_birth_age_days(path)
            out.append(TokenRecord(
                server=srv_dir.name,
                label=path.stem,
                path=path,
                age_days=age,
                has_refresh=bool(data.get("refresh_token") or data.get("refreshToken")),
                scopes=data.get("scopes") or data.get("scope") or [],
                tier=classify_age(age),
                notes="",
            ))
    return out


def scan_claude_json_keys() -> list[TokenRecord]:
    """Scan ~/.claude.json for any apiKey / refreshToken values inside
    mcpServers entries and report their presence (no key value is read)."""
    if not CLAUDE_CONFIG.is_file():
        return []
    out: list[TokenRecord] = []
    age_days = file_birth_age_days(CLAUDE_CONFIG)
    try:
        with CLAUDE_CONFIG.open() as f:
            cfg = json.load(f)
    except Exception:
        return out
    for proj_path, proj_cfg in (cfg.get("projects") or {}).items():
        servers = (proj_cfg.get("mcpServers") or {})
        for srv_name, srv_cfg in servers.items():
            env = srv_cfg.get("env") or {}
            secret_keys = [k for k in env if any(
                tag in k.upper() for tag in ("KEY", "TOKEN", "SECRET", "PASS")
            )]
            if not secret_keys:
                continue
            out.append(TokenRecord(
                server=f"{srv_name} (~/.claude.json)",
                label=f"{Path(proj_path).name}: {','.join(secret_keys)}",
                path=CLAUDE_CONFIG,
                age_days=age_days,
                has_refresh=False,
                scopes=[],
                tier=classify_age(age_days),
                notes="env var; rotation depends on provider",
            ))
    return out


TIER_BADGE = {"green": "🟢 green", "yellow": "🟡 yellow", "orange": "🟠 orange", "red": "🔴 red"}
TIER_ACTION = {
    "green": "fresh — no action",
    "yellow": "rotate this quarter",
    "orange": "rotate now",
    "red": "long overdue — rotate immediately",
}


def render_report(records: list[TokenRecord], threshold: int) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    by_tier: dict[str, list[TokenRecord]] = {"red": [], "orange": [], "yellow": [], "green": []}
    for r in records:
        by_tier[r.tier].append(r)

    over_threshold = [r for r in records if r.age_days >= threshold]

    out = [
        f"# MCP token age inventory — {today}",
        "",
        f"_Source: {MCP_SERVERS_DIR}/<server>/tokens/, {CLAUDE_CONFIG}._",
        f"_Tiers: green <30d, yellow 30-90d, orange 90-180d, red 180+d. Threshold for action callout: {threshold}d._",
        "",
        "## Summary",
        "",
        f"| Tier | Count | Action |",
        f"|---|---|---|",
    ]
    for tier in ("red", "orange", "yellow", "green"):
        out.append(f"| {TIER_BADGE[tier]} | {len(by_tier[tier])} | {TIER_ACTION[tier]} |")
    out.append("")
    out.append(f"**Tokens at or over {threshold}d threshold: {len(over_threshold)}**")
    out.append("")

    out.append("## Detail (oldest first)")
    out.append("")
    out.append("| Tier | Server | Label | Age | Has refresh | Notes |")
    out.append("|---|---|---|---|---|---|")
    for r in sorted(records, key=lambda x: -x.age_days):
        out.append(
            f"| {TIER_BADGE[r.tier]} | {r.server} | {r.label} | "
            f"{r.age_days}d | {'yes' if r.has_refresh else 'no'} | {r.notes or '—'} |"
        )
    out.append("")

    if any(r.tier in ("red", "orange") for r in records):
        out.append("## Recommended next steps")
        out.append("")
        out.append("1. Rotate the orange/red tokens above this week.")
        out.append("2. For google-workspace tokens, re-run the MCP server's `--auth-only` flow:")
        out.append("   ```")
        out.append("   ~/Winnie/mcp-servers/google-workspace/venv/bin/python \\")
        out.append("     ~/Winnie/mcp-servers/google-workspace/server.py \\")
        out.append("     --account <label> --auth-only")
        out.append("   ```")
        out.append("3. After rotating, the new token file's birth time resets the age counter.")
        out.append("")

    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--threshold-days", type=int, default=90,
                        help="Age threshold for action callout (default: 90)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print to stdout; don't write the audit file")
    parser.add_argument("--out-path", help="Override output path")
    args = parser.parse_args()

    start = time.time()
    tenant_cfg = load_tenant_cfg(args.tenant)
    vault = vault_path(tenant_cfg)

    records = (
        scan_google_workspace_tokens()
        + scan_other_mcp_tokens()
        + scan_claude_json_keys()
    )

    print(f"=== {SCRIPT_NAME} (tenant={args.tenant}) ===")
    print(f"records found: {len(records)}")
    by_tier: dict[str, int] = {"green": 0, "yellow": 0, "orange": 0, "red": 0}
    for r in records:
        by_tier[r.tier] += 1
    for tier in ("red", "orange", "yellow", "green"):
        print(f"  {TIER_BADGE[tier]:18s} {by_tier[tier]}")

    report = render_report(records, args.threshold_days)
    if args.dry_run:
        print()
        print(report)
    else:
        out_dir = vault / "HFO" / "OPSEC" / "Audits"
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = Path(args.out_path) if args.out_path else (out_dir / f"{today}-mcp-token-age.md")
        out_path.write_text(report)
        print(f"\nwrote: {out_path}")

    over_threshold = sum(1 for r in records if r.age_days >= args.threshold_days)
    emit_telemetry(SCRIPT_NAME, outcome="success",
                   records_total=len(records),
                   tier_red=by_tier["red"],
                   tier_orange=by_tier["orange"],
                   tier_yellow=by_tier["yellow"],
                   tier_green=by_tier["green"],
                   over_threshold=over_threshold,
                   threshold_days=args.threshold_days,
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
