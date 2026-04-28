#!/usr/bin/env python3
"""Render a Tier 1 / 2 / 3 proposal from a scoped deal.

This is the Python implementation that the proposal-composer SKILL
delegates to (or can be invoked directly for batch / scripted use).

Usage:
  compose-proposal.py --tenant phil-howard --entity ccg --tier 2 \
    --lead-slug eli-lilly-brain-health-support
  compose-proposal.py --tenant phil-howard --entity alpen-tech --tier 1 \
    --deal-json /tmp/scope.json
  compose-proposal.py --tenant phil-howard --entity ccg --tier 3 \
    --lead-slug roche-program-development --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
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
from _template_renderer import render, collect_variables  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "compose-proposal"
LEADS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/leads.db"))


# ──────────────────────────────────────────────────────────────────────────────
# Tenant + entity loading
# ──────────────────────────────────────────────────────────────────────────────

def load_tenant_config(tenant_id: str) -> dict:
    path = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    if not path.is_file():
        sys.exit(f"error: tenant config not found: {path}")
    with path.open() as f:
        return yaml.safe_load(f) or {}


def find_entity(config: dict, entity_id: str) -> dict:
    for e in config.get("entities") or []:
        if e.get("id") == entity_id:
            return e
    sys.exit(f"error: entity {entity_id!r} not in tenant config")


def find_principal(config: dict, role: str = "ceo") -> dict:
    for p in config.get("principals") or []:
        if p.get("role") == role:
            return p
    # Fall back to first
    principals = config.get("principals") or []
    if principals:
        return principals[0]
    sys.exit("error: no principals defined in tenant config")


def find_partner(config: dict) -> dict | None:
    for p in config.get("principals") or []:
        if p.get("role") == "partner":
            return p
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Template loading (entity > tenant > default resolution)
# ──────────────────────────────────────────────────────────────────────────────

def load_template(tier: int, entity_id: str, tenant_id: str) -> tuple[Path, str]:
    name = f"proposal-tier-{tier}.md"
    candidates = [
        PLATFORM_ROOT / "templates" / entity_id / name,
        PLATFORM_ROOT / "templates" / tenant_id / name,
        PLATFORM_ROOT / "templates" / "default" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c, c.read_text()
    sys.exit(f"error: no template found for tier {tier} (looked in {[str(c) for c in candidates]})")


# ──────────────────────────────────────────────────────────────────────────────
# Lead lookup (from leads.db OR per-opp markdown)
# ──────────────────────────────────────────────────────────────────────────────

def load_lead_from_db(slug: str) -> dict | None:
    if not LEADS_DB.is_file():
        return None
    conn = sqlite3.connect(LEADS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM lead WHERE id = ?", (slug,)).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def lead_to_deal_context(lead: dict, override_tier: int | None) -> dict:
    """Map leads.db row fields to {{deal.*}} template variables."""
    return {
        "client_name": lead.get("display_name") or lead.get("company_name") or lead["id"],
        "client_signatory_name": lead.get("primary_contact"),
        "client_signatory_title": "TBD",
        "industry": "TBD",
        "value": lead.get("value_estimate"),
        "tier": override_tier if override_tier is not None else lead.get("tier"),
        "problem_statement": "TBD — fill from discovery notes",
        "target_outcome": "TBD",
        "success_metric": "TBD",
        "engagement_name": lead.get("display_name"),
        "contracting_entity": "TBD — entity legal name",
        "msa_date": "TBD",
        "sow_number": "1",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Build context
# ──────────────────────────────────────────────────────────────────────────────

def build_context(tenant_cfg: dict, entity: dict, sig_ctx: dict,
                  deal: dict, today: datetime) -> dict:
    return {
        "tenant": {
            "id": tenant_cfg["tenant"]["id"],
            **sig_ctx,
            "business_address": entity.get("address", "TBD"),
        },
        "entity": entity,
        "deal": deal,
        "today": today.strftime("%Y-%m-%d"),
        "year": today.year,
        "quarter": f"Q{(today.month - 1) // 3 + 1} {today.year}",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Voice sweep
# ──────────────────────────────────────────────────────────────────────────────

def voice_sweep_required(entity: dict) -> bool:
    return bool(((entity.get("brand") or {}).get("no_em_dash")))


def run_voice_sweep(path: Path) -> str:
    """Returns 'pass' / 'fail' / 'skipped' — never raises."""
    sweep = Path(os.path.expanduser("~/Winnie/bin/voice-sweep.sh"))
    if not sweep.is_file():
        return "skipped"
    result = subprocess.run(
        [str(sweep), str(path)],
        capture_output=True, text=True, timeout=10,
    )
    return "pass" if result.returncode == 0 else "fail"


# ──────────────────────────────────────────────────────────────────────────────
# State machine update
# ──────────────────────────────────────────────────────────────────────────────

def transition_lead_to_proposed(slug: str, value: int | None) -> bool:
    if not LEADS_DB.is_file():
        return False
    try:
        conn = sqlite3.connect(LEADS_DB)
        cur = conn.execute("SELECT stage FROM lead WHERE id = ?", (slug,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return False
        prev_stage = row[0]
        # Don't downgrade
        if prev_stage in ("WON", "LOST", "DISQUALIFIED"):
            conn.close()
            return False
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute(
            "UPDATE lead SET stage='PROPOSED', stage_entered_date=?, value_estimate=COALESCE(?, value_estimate) WHERE id = ?",
            (today, value, slug),
        )
        conn.execute("""
            INSERT INTO lead_history (lead_id, occurred_at, source, event_type, from_stage, to_stage, description)
            VALUES (?, ?, 'compose-proposal', 'stage_change', ?, 'PROPOSED', 'Proposal composed')
        """, (slug, datetime.now().isoformat(timespec='seconds'), prev_stage))
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        print(f"  ! state transition failed: {e}", file=sys.stderr)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────────────────

def determine_output_path(tenant_cfg: dict, lead_slug: str, tier: int) -> Path:
    vault = Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"]))
    out_dir = vault / "Sales" / "Proposals"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{lead_slug}-tier-{tier}.md"


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--entity", required=True)
    parser.add_argument("--tier", required=True, type=int, choices=[1, 2, 3])
    parser.add_argument("--lead-slug", help="lead id to load from leads.db")
    parser.add_argument("--deal-json", help="path to JSON file with deal context")
    parser.add_argument("--dry-run", action="store_true", help="render to stdout, don't write or transition")
    parser.add_argument("--signatory", help="principal id of signer (overrides entity default; e.g., 'phil' for CCG to sign as COO)")
    args = parser.parse_args()

    if not (args.lead_slug or args.deal_json):
        sys.exit("error: must pass --lead-slug or --deal-json")

    start = time.time()
    tenant_cfg = load_tenant_config(args.tenant)
    entity = find_entity(tenant_cfg, args.entity)
    sig_ctx = build_signatory_context(tenant_cfg, args.entity, args.signatory)

    template_path, template_text = load_template(args.tier, args.entity, args.tenant)

    # Build deal context
    if args.lead_slug:
        lead = load_lead_from_db(args.lead_slug)
        if not lead:
            sys.exit(f"error: lead {args.lead_slug!r} not found in leads.db; run regenerate-leads-index first")
        deal = lead_to_deal_context(lead, args.tier)
        lead_slug_for_output = args.lead_slug
    else:
        with open(args.deal_json) as f:
            deal = json.load(f)
        lead_slug_for_output = deal.get("client_name", "unknown").lower().replace(" ", "-")

    context = build_context(tenant_cfg, entity, sig_ctx, deal, datetime.now())

    print(f"=== compose-proposal: tier {args.tier}, entity {args.entity}, tenant {args.tenant} ===")
    print(f"template:   {template_path}")
    print(f"variables:  {len(collect_variables(template_text))} unique")

    rendered = render(template_text, context)
    print(f"resolved:   {len(rendered.resolved)}")
    print(f"unresolved: {len(rendered.unresolved)}")
    if rendered.unresolved:
        print("  unresolved variables (will be left as {{...}} in output):")
        for v in rendered.unresolved:
            print(f"    - {{{{{v}}}}}")
    print()

    if args.dry_run:
        print("--- rendered output (dry-run) ---")
        print(rendered.text)
        print("--- end ---")
        emit_telemetry(
            SCRIPT_NAME, outcome="success",
            tier=args.tier, entity=args.entity,
            variables_resolved=len(rendered.resolved),
            variables_unresolved=len(rendered.unresolved),
            voice_sweep="skipped",
            dry_run=True,
            duration_seconds=round(time.time() - start, 2),
        )
        return 0

    output_path = determine_output_path(tenant_cfg, lead_slug_for_output, args.tier)
    if output_path.exists():
        backup = output_path.with_suffix(f".prev-{int(time.time())}.md")
        shutil.copy2(output_path, backup)
        print(f"  prior version backed up to {backup.name}")
    output_path.write_text(rendered.text)
    print(f"wrote: {output_path}")

    sweep_result = "skipped"
    if voice_sweep_required(entity):
        sweep_result = run_voice_sweep(output_path)
        print(f"voice sweep: {sweep_result}")

    transitioned = False
    if args.lead_slug:
        transitioned = transition_lead_to_proposed(args.lead_slug, deal.get("value"))
        if transitioned:
            print(f"leads.db: transitioned {args.lead_slug} -> PROPOSED")

    emit_telemetry(
        SCRIPT_NAME, outcome="success",
        tier=args.tier, entity=args.entity, lead_slug=args.lead_slug or "manual",
        variables_resolved=len(rendered.resolved),
        variables_unresolved=len(rendered.unresolved),
        voice_sweep=sweep_result,
        state_transitioned=int(transitioned),
        duration_seconds=round(time.time() - start, 2),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
