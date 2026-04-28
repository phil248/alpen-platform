#!/usr/bin/env python3
"""Render an MSA from a deal context.

Companion to compose-proposal.py and compose-sow.py. Workflow position:

  WON lead → optionally: compose-msa (umbrella) → compose-sow (per project)

Use cases:
  - First-time engagement with a client; no MSA in place yet
  - Renewing / refreshing an MSA when the prior one expires

Output:
  - Markdown rendered to ${VAULT}/Legal/Contracts/<msa-slug>.md
  - Row inserted into contracts.db: type=MSA, status=DRAFT, parent=NULL
  - Voice-swept if entity has brand.no_em_dash=true

Usage:
  compose-msa.py --tenant phil-howard --entity ccg \
    --client-name "Acme Corp" \
    --client-legal-name "Acme Corporation" \
    --client-state "Delaware" \
    --client-address "123 Market St, San Francisco, CA 94103" \
    --client-signatory-name "Sarah Chen" \
    --client-signatory-title "VP Engineering" \
    --client-signatory-email "sarah@acme.com" \
    --effective-date 2026-05-01

  compose-msa.py --tenant phil-howard --entity ccg \
    --client-name "Acme Corp" --dry-run    # minimal — most fields TBD
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import build_signatory_context, emit_telemetry, find_signatory  # noqa: E402
from _template_renderer import render  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "compose-msa"
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    if not p.is_file():
        sys.exit(f"error: tenant config not found: {p}")
    with p.open() as f:
        return yaml.safe_load(f) or {}


def find_entity(cfg: dict, entity_id: str) -> dict:
    for e in cfg.get("entities") or []:
        if e["id"] == entity_id:
            return e
    sys.exit(f"error: entity {entity_id!r} not in tenant config")


def find_principal(cfg: dict, role: str = "ceo") -> dict:
    for p in cfg.get("principals") or []:
        if p.get("role") == role:
            return p
    return (cfg.get("principals") or [{}])[0]


def load_template(entity_id: str, tenant_id: str) -> tuple[Path, str]:
    name = "msa-template.md"
    candidates = [
        PLATFORM_ROOT / "templates" / entity_id / name,
        PLATFORM_ROOT / "templates" / tenant_id / name,
        PLATFORM_ROOT / "templates" / "default" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c, c.read_text()
    sys.exit("error: msa-template.md not found in any template dir")


def slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or "client"


def insert_msa_row(slug: str, deal: dict, entity: dict, tenant_id: str,
                   principal_name: str, vault_path: str) -> bool:
    """Insert MSA row into contracts.db with status=DRAFT, type=MSA, parent=NULL."""
    if not CONTRACTS_DB.is_file():
        print("  ! contracts.db not found; run regenerate-contracts-index first", file=sys.stderr)
        return False
    conn = sqlite3.connect(CONTRACTS_DB)
    try:
        conn.execute("""
            INSERT INTO contract (
              id, tenant_id, entity_id, contract_type, parent_contract_id,
              display_name, contracting_entity_us, contracting_entity_them,
              signatory_us, signatory_them, status, effective_date,
              total_value, governing_law, vault_path
            ) VALUES (?, ?, ?, 'MSA', NULL, ?, ?, ?, ?, ?, 'DRAFT', ?, NULL, ?, ?)
        """, (
            slug, tenant_id, entity["id"],
            f"MSA — {deal['client_name']} × {entity.get('display_name', entity['id'])}",
            entity.get("legal_name"),
            deal.get("client_legal_name") or deal["client_name"],
            principal_name,
            deal.get("client_signatory_name"),
            deal.get("effective_date"),
            entity.get("state_of_organization"),
            vault_path,
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError as e:
        print(f"  ! integrity error (likely duplicate slug): {e}", file=sys.stderr)
        # Try to update existing instead
        conn.execute(
            "UPDATE contract SET status='DRAFT', vault_path=? WHERE id = ?",
            (vault_path, slug),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--entity", required=True, help="Service Provider entity id (ccg | alpen-tech)")
    parser.add_argument("--client-name", required=True, help="Display name of client")
    parser.add_argument("--client-legal-name", help="Full legal entity name (defaults to --client-name)")
    parser.add_argument("--client-state", help="State of organization (e.g., Delaware)")
    parser.add_argument("--client-entity-descriptor", help="e.g., 'a Delaware corporation' (auto-generated if --client-state given)")
    parser.add_argument("--client-address", help="Physical office address")
    parser.add_argument("--client-signatory-name", help="Name of person signing for client")
    parser.add_argument("--client-signatory-title", help="Title of signatory")
    parser.add_argument("--client-signatory-email", help="Email")
    parser.add_argument("--effective-date", help="ISO date YYYY-MM-DD; defaults to today")
    parser.add_argument("--slug", help="Override the contract slug (default: msa-<client-slug>-<YYYY>)")
    parser.add_argument("--signatory", help="principal id of OUR signer (overrides entity default)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = time.time()
    tenant_cfg = load_tenant_cfg(args.tenant)
    entity = find_entity(tenant_cfg, args.entity)
    sig_ctx = build_signatory_context(tenant_cfg, args.entity, args.signatory)
    template_path, template_text = load_template(args.entity, args.tenant)

    today = datetime.now()
    effective_date = args.effective_date or today.strftime("%Y-%m-%d")
    client_legal_name = args.client_legal_name or args.client_name
    client_state = args.client_state or "TBD"
    client_descriptor = args.client_entity_descriptor or (
        f"a {client_state} corporation" if args.client_state else "TBD"
    )

    deal = {
        "client_name":             args.client_name,
        "client_legal_name":       client_legal_name,
        "client_entity_descriptor": client_descriptor,
        "client_address":          args.client_address or "TBD",
        "client_signatory_name":   args.client_signatory_name or "TBD",
        "client_signatory_title":  args.client_signatory_title or "TBD",
        "client_signatory_email":  args.client_signatory_email or "TBD",
        "effective_date":          effective_date,
    }

    context = {
        "tenant": {**sig_ctx},
        "entity":   entity,
        "deal":     deal,
        "today":    today.strftime("%Y-%m-%d"),
    }

    rendered = render(template_text, context)

    msa_slug = args.slug or f"msa-{slugify(args.client_name)}-{today.year}"

    print(f"=== compose-msa ===")
    print(f"client:    {args.client_name}")
    print(f"entity:    {entity.get('legal_name')} ({args.entity})")
    print(f"slug:      {msa_slug}")
    print(f"effective: {effective_date}")
    print(f"template:  {template_path}")
    print(f"resolved:  {len(rendered.resolved)}, unresolved: {len(rendered.unresolved)}")
    if rendered.unresolved:
        print(f"  unresolved: {rendered.unresolved}")

    if args.dry_run:
        print()
        print("--- rendered (first 60 lines) ---")
        for line in rendered.text.splitlines()[:60]:
            print(line)
        print("--- end preview ---")
        emit_telemetry(SCRIPT_NAME, outcome="success", dry_run=True,
                       entity=args.entity, client=args.client_name,
                       variables_resolved=len(rendered.resolved),
                       variables_unresolved=len(rendered.unresolved))
        return 0

    vault = Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"]))
    out_dir = vault / "Legal" / "Contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{msa_slug}.md"
    if out_path.exists():
        backup = out_path.with_suffix(f".prev-{int(time.time())}.md")
        shutil.copy2(out_path, backup)
        print(f"  prior backed up to {backup.name}")
    out_path.write_text(rendered.text)
    print(f"wrote: {out_path}")

    inserted = insert_msa_row(
        msa_slug, deal, entity, args.tenant, sig_ctx["signatory_name"],
        str(out_path.relative_to(vault)),
    )
    if inserted:
        print(f"contracts.db: inserted MSA row '{msa_slug}' (status=DRAFT)")

    sweep = "skipped"
    if (entity.get("brand") or {}).get("no_em_dash"):
        result = subprocess.run(
            [str(Path.home() / "Winnie" / "bin" / "voice-sweep.sh"), str(out_path)],
            capture_output=True, text=True, timeout=10,
        )
        sweep = "pass" if result.returncode == 0 else "fail"
        print(f"voice sweep: {sweep}")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   entity=args.entity, client=args.client_name,
                   variables_resolved=len(rendered.resolved),
                   variables_unresolved=len(rendered.unresolved),
                   contract_inserted=int(inserted),
                   voice_sweep=sweep,
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
