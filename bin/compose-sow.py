#!/usr/bin/env python3
"""Render an SOW from a WON deal under an existing MSA.

Companion to compose-proposal.py. Workflow:

  WON lead   →  compose-proposal  → produced and accepted proposal
                ↓
                Use this script to render the SOW that papers the engagement.
                Inserts a stub contract row into contracts.db (status=DRAFT,
                type=SOW, parent_msa=...).
                Optionally creates a stub engagements.db row pre-populated
                with deliverables for the kickoff.

Usage:
  compose-sow.py --tenant phil-howard --entity ccg \
    --lead-slug eli-lilly-brain-health-support --tier 2 \
    --msa-contract-id msa-eli-lilly-2026
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402
from _template_renderer import render, collect_variables  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "compose-sow"
LEADS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/leads.db"))
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))
ENGAGEMENTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/engagements.db"))


def load_tenant_config(tenant_id: str) -> dict:
    path = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    if not path.is_file():
        sys.exit(f"error: tenant config not found: {path}")
    with path.open() as f:
        return yaml.safe_load(f) or {}


def find_entity(config: dict, entity_id: str) -> dict:
    for e in config.get("entities") or []:
        if e["id"] == entity_id:
            return e
    sys.exit(f"error: entity {entity_id!r} not in tenant config")


def find_principal(config: dict, role: str = "ceo") -> dict:
    for p in config.get("principals") or []:
        if p.get("role") == role:
            return p
    return (config.get("principals") or [{}])[0]


def load_template(entity_id: str, tenant_id: str) -> tuple[Path, str]:
    name = "sow-template.md"
    candidates = [
        PLATFORM_ROOT / "templates" / entity_id / name,
        PLATFORM_ROOT / "templates" / tenant_id / name,
        PLATFORM_ROOT / "templates" / "default" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c, c.read_text()
    sys.exit(f"error: no SOW template found")


def load_lead(slug: str) -> dict | None:
    if not LEADS_DB.is_file():
        return None
    conn = sqlite3.connect(LEADS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM lead WHERE id = ?", (slug,)).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_sow_contract(slug: str, lead: dict, msa_id: str, tier: int, value: int | None,
                        tenant_id: str, entity_id: str, vault_path: str,
                        principal: dict, signatory_them: str | None) -> bool:
    if not CONTRACTS_DB.is_file():
        print("  ! contracts.db missing; run regenerate-contracts-index first", file=sys.stderr)
        return False
    conn = sqlite3.connect(CONTRACTS_DB)
    try:
        conn.execute("""
            INSERT INTO contract (
              id, tenant_id, entity_id, contract_type, parent_contract_id,
              display_name, contracting_entity_us, contracting_entity_them,
              signatory_us, signatory_them, status,
              effective_date, total_value, lead_id, vault_path
            ) VALUES (?, ?, ?, 'SOW', ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?)
        """, (
            slug, tenant_id, entity_id, msa_id,
            lead.get("display_name") or slug,
            "TBD",
            lead.get("company_name") or lead.get("display_name") or "TBD",
            principal["name"],
            signatory_them,
            datetime.now().date().isoformat(),
            value,
            lead["id"],
            vault_path,
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError as e:
        # Already exists — update status to DRAFT
        print(f"  ! contract row already exists ({e}); updating to DRAFT", file=sys.stderr)
        conn.execute("UPDATE contract SET status='DRAFT', total_value=COALESCE(?, total_value) WHERE id = ?", (value, slug))
        conn.commit()
        return True
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--entity", required=True)
    parser.add_argument("--lead-slug", required=True)
    parser.add_argument("--tier", required=True, type=int, choices=[1, 2, 3])
    parser.add_argument("--msa-contract-id", required=True)
    parser.add_argument("--sow-number", default="1")
    parser.add_argument("--signatory-them", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = time.time()
    tenant_cfg = load_tenant_config(args.tenant)
    entity = find_entity(tenant_cfg, args.entity)
    principal = find_principal(tenant_cfg)
    template_path, template_text = load_template(args.entity, args.tenant)
    lead = load_lead(args.lead_slug)
    if not lead:
        sys.exit(f"error: lead {args.lead_slug!r} not found in leads.db")

    today = datetime.now()
    sow_slug = f"{args.lead_slug}-sow-{args.sow_number}"
    sow_end = today + timedelta(weeks=8 if args.tier == 2 else (24 if args.tier == 3 else 4))

    deal = {
        "client_name": lead.get("display_name"),
        "client_signatory_name": args.signatory_them or lead.get("primary_contact"),
        "value": lead.get("value_estimate"),
        "tier": args.tier,
        "msa_date": "TBD",
        "sow_number": args.sow_number,
        "sow_effective_date": today.strftime("%Y-%m-%d"),
        "sow_end_date": sow_end.strftime("%Y-%m-%d"),
        "services_summary": "TBD — fill from accepted proposal",
        "deliverable_1": "TBD",
        "deliverable_2": "TBD",
        "deliverable_3": "TBD",
        "deliverable_1_criteria": "TBD",
        "deliverable_2_criteria": "TBD",
        "deliverable_3_criteria": "TBD",
        "deliverable_1_due": "TBD",
        "deliverable_2_due": "TBD",
        "deliverable_3_due": "TBD",
        "kickoff_date": (today + timedelta(days=14)).strftime("%Y-%m-%d"),
        "discovery_end": (today + timedelta(weeks=1)).strftime("%Y-%m-%d"),
        "midpoint_demo": (today + timedelta(weeks=4)).strftime("%Y-%m-%d"),
        "final_delivery": (today + timedelta(weeks=7)).strftime("%Y-%m-%d"),
        "acceptance_target": (today + timedelta(weeks=8)).strftime("%Y-%m-%d"),
        "payment_kickoff": (lead.get("value_estimate") or 0) // 4,
        "payment_midpoint": (lead.get("value_estimate") or 0) // 2,
        "payment_final": (lead.get("value_estimate") or 0) // 4,
        "principal_role": "Engagement lead",
        "principal_allocation": "primary",
        "partner_role": "Subject matter contributor",
        "partner_allocation": "as scope requires",
        "contributor_3_name": "TBD",
        "contributor_3_role": "TBD",
        "contributor_3_allocation": "TBD",
        "client_poc_name": lead.get("primary_contact") or "TBD",
        "client_poc_title": "TBD",
        "client_poc_email": "TBD",
        "client_sponsor_name": "TBD",
        "client_sponsor_title": "TBD",
        "stakeholder_session_count": "2",
        "client_decision_areas": "TBD",
        "client_delegate_name": "TBD",
        "access_systems": "TBD",
        "assumption_1": "TBD",
        "assumption_2": "TBD",
        "assumption_3": "TBD",
        "dependency_1": "TBD",
        "dependency_2": "TBD",
        "out_of_scope_1": "TBD",
        "out_of_scope_2": "TBD",
        "out_of_scope_3": "TBD",
        "contracting_entity": "TBD — entity legal name",
    }

    context = {
        "tenant": {
            "principal_name": principal["name"],
            "principal_title": principal.get("role", "ceo").upper(),
            "partner_name": "TBD",
        },
        "entity": entity,
        "principal": principal,
        "deal": deal,
        "today": today.strftime("%Y-%m-%d"),
    }

    print(f"=== compose-sow: {args.lead_slug} (tier {args.tier}, msa={args.msa_contract_id}) ===")
    print(f"template: {template_path}")
    rendered = render(template_text, context)
    print(f"resolved: {len(rendered.resolved)}, unresolved: {len(rendered.unresolved)}")

    if args.dry_run:
        print("--- rendered (dry-run) ---")
        print(rendered.text)
        emit_telemetry(SCRIPT_NAME, outcome="success", dry_run=True,
                       lead_slug=args.lead_slug, tier=args.tier,
                       variables_resolved=len(rendered.resolved),
                       variables_unresolved=len(rendered.unresolved))
        return 0

    vault = Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"]))
    out_dir = vault / "Legal" / "Contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{sow_slug}.md"
    if output_path.exists():
        backup = output_path.with_suffix(f".prev-{int(time.time())}.md")
        shutil.copy2(output_path, backup)
        print(f"  prior backed up to {backup.name}")
    output_path.write_text(rendered.text)
    print(f"wrote: {output_path}")

    # Insert SOW row in contracts.db
    rel_path = str(output_path.relative_to(vault))
    inserted = insert_sow_contract(
        sow_slug, lead, args.msa_contract_id, args.tier,
        lead.get("value_estimate"), args.tenant, args.entity,
        rel_path, principal, args.signatory_them,
    )
    if inserted:
        print(f"contracts.db: inserted SOW row '{sow_slug}' (status=DRAFT, parent={args.msa_contract_id})")

    # Voice sweep
    sweep = "skipped"
    if (entity.get("brand") or {}).get("no_em_dash"):
        result = subprocess.run(
            [str(Path.home() / "Winnie" / "bin" / "voice-sweep.sh"), str(output_path)],
            capture_output=True, text=True, timeout=10,
        )
        sweep = "pass" if result.returncode == 0 else "fail"
        print(f"voice sweep: {sweep}")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   lead_slug=args.lead_slug, tier=args.tier,
                   variables_resolved=len(rendered.resolved),
                   variables_unresolved=len(rendered.unresolved),
                   contract_inserted=int(inserted),
                   voice_sweep=sweep,
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
