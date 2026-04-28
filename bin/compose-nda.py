#!/usr/bin/env python3
"""Render a one-way NDA / Confidentiality Agreement.

Two directions:
  --direction inbound (default) — client shares with us; we are Receiving Party
  --direction outbound          — we share with partner; we are Disclosing Party

Output:
  - Markdown rendered to ${VAULT}/Legal/Contracts/<nda-slug>.md
  - Row inserted into contracts.db: type=NDA, status=DRAFT, parent=NULL

Usage:
  # Inbound (most common): prospective client shares data with us
  compose-nda.py --tenant phil-howard --entity ccg --direction inbound \
    --counterparty-name "Acme Corp" \
    --counterparty-legal-name "Acme Corporation" \
    --counterparty-state "Delaware" \
    --counterparty-address "123 Market St, San Francisco, CA 94103" \
    --counterparty-signatory-name "Sarah Chen" \
    --counterparty-signatory-title "VP HR" \
    --project-description "Brain-health program scoping for Acme's 5,000-person workforce" \
    --information-categories "Employee survey data, internal program metrics, leadership interviews" \
    --beginning-ci-date 2026-05-01

  # Outbound: we share methodology with a partner who's evaluating us
  compose-nda.py --tenant phil-howard --entity alpen-tech --direction outbound \
    --counterparty-name "PartnerCo" \
    --counterparty-legal-name "PartnerCo Inc." \
    --project-description "Evaluation of Alpen Platform for joint deployment" \
    --information-categories "Platform architecture, IP MCP source, tier-ladder pricing"

Mutual NDAs (both sides as discloser AND receiver) deferred to v0.2 — that
template has different structure (symmetric obligations rather than one-way
contractor-protects-discloser).
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
from _regenerator_lib import emit_telemetry  # noqa: E402
from _template_renderer import render  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "compose-nda"
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
    name = "nda-template.md"
    candidates = [
        PLATFORM_ROOT / "templates" / entity_id / name,
        PLATFORM_ROOT / "templates" / tenant_id / name,
        PLATFORM_ROOT / "templates" / "default" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c, c.read_text()
    sys.exit("error: nda-template.md not found in any template dir")


def slugify(s: str) -> str:
    return (re.sub(r"[^A-Za-z0-9]+", "-", s.lower()).strip("-")[:60]) or "party"


def insert_nda_row(slug: str, deal: dict, entity: dict, tenant_id: str,
                   our_signatory_name: str, vault_path: str) -> bool:
    """Insert NDA row into contracts.db with type=NDA, status=DRAFT, parent=NULL."""
    if not CONTRACTS_DB.is_file():
        print("  ! contracts.db not found; run regenerate-contracts-index first", file=sys.stderr)
        return False
    conn = sqlite3.connect(CONTRACTS_DB)
    try:
        # Both the "us" and "them" map differs by direction. We always store
        # OUR entity in contracting_entity_us regardless of direction (it's
        # who we are in the contract). The counterparty name goes in _them.
        counterparty_name = deal.get("disclosing_legal_name") if deal["_direction"] == "inbound" else deal.get("receiving_legal_name")
        counterparty_signatory = deal.get("disclosing_signatory_name") if deal["_direction"] == "inbound" else deal.get("receiving_signatory_name")
        conn.execute("""
            INSERT INTO contract (
              id, tenant_id, entity_id, contract_type, parent_contract_id,
              display_name, contracting_entity_us, contracting_entity_them,
              signatory_us, signatory_them, status, effective_date,
              total_value, governing_law, vault_path
            ) VALUES (?, ?, ?, 'NDA', NULL, ?, ?, ?, ?, ?, 'DRAFT', ?, NULL, ?, ?)
        """, (
            slug, tenant_id, entity["id"],
            f"NDA — {counterparty_name} × {entity.get('display_name', entity['id'])}",
            entity.get("legal_name"),
            counterparty_name,
            our_signatory_name,
            counterparty_signatory,
            deal.get("beginning_ci_sharing_date"),
            entity.get("state_of_organization"),
            vault_path,
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError as e:
        print(f"  ! integrity error: {e}", file=sys.stderr)
        return False
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--entity", required=True)
    parser.add_argument("--direction", choices=["inbound", "outbound"], default="inbound",
                        help="inbound = counterparty shares with us; outbound = we share with counterparty")
    parser.add_argument("--counterparty-name", required=True)
    parser.add_argument("--counterparty-legal-name")
    parser.add_argument("--counterparty-state")
    parser.add_argument("--counterparty-entity-descriptor")
    parser.add_argument("--counterparty-address")
    parser.add_argument("--counterparty-signatory-name")
    parser.add_argument("--counterparty-signatory-title")
    parser.add_argument("--project-description", required=True,
                        help="Attachment A project description")
    parser.add_argument("--information-categories",
                        help="Attachment A information categories (multiline OK)")
    parser.add_argument("--beginning-ci-date",
                        help="ISO YYYY-MM-DD; defaults to today")
    parser.add_argument("--slug")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = time.time()
    tenant_cfg = load_tenant_cfg(args.tenant)
    entity = find_entity(tenant_cfg, args.entity)
    principal = find_principal(tenant_cfg)
    template_path, template_text = load_template(args.entity, args.tenant)

    today = datetime.now()
    cp_legal = args.counterparty_legal_name or args.counterparty_name
    cp_state = args.counterparty_state or "TBD"
    cp_descriptor = args.counterparty_entity_descriptor or (
        f"a {cp_state} corporation" if args.counterparty_state else "TBD"
    )
    beginning_date = args.beginning_ci_date or today.strftime("%Y-%m-%d")

    # Build "us" side from entity + principal
    our_legal = entity.get("legal_name", "TBD")
    our_address = entity.get("address", "TBD")
    our_descriptor = entity.get("entity_descriptor", "TBD")
    our_signatory_name = principal["name"]
    # Title: temporarily uses principal role; will use entity.signatories[].title once
    # the per-entity-signatory schema lands. For now: "President, <entity>" matches the
    # pattern Phil + Krystal currently sign as on the InnoSync executed CDA.
    our_signatory_title = f"President, {our_legal}"

    # Build deal context based on direction
    if args.direction == "inbound":
        # Counterparty discloses; we receive
        deal = {
            "_direction":                  "inbound",
            "disclosing_legal_name":       cp_legal,
            "disclosing_entity_descriptor": cp_descriptor,
            "disclosing_address":          args.counterparty_address or "TBD",
            "disclosing_short_name":       args.counterparty_name,
            "disclosing_signatory_name":   args.counterparty_signatory_name or "TBD",
            "disclosing_signatory_title":  args.counterparty_signatory_title or "TBD",
            "receiving_legal_name":        our_legal,
            "receiving_address":           our_address,
            "receiving_signatory_name":    our_signatory_name,
            "receiving_signatory_title":   our_signatory_title,
        }
    else:
        # We disclose; counterparty receives
        deal = {
            "_direction":                  "outbound",
            "disclosing_legal_name":       our_legal,
            "disclosing_entity_descriptor": our_descriptor,
            "disclosing_address":          our_address,
            "disclosing_short_name":       entity.get("display_name", our_legal),
            "disclosing_signatory_name":   our_signatory_name,
            "disclosing_signatory_title":  our_signatory_title,
            "receiving_legal_name":        cp_legal,
            "receiving_address":           args.counterparty_address or "TBD",
            "receiving_signatory_name":    args.counterparty_signatory_name or "TBD",
            "receiving_signatory_title":   args.counterparty_signatory_title or "TBD",
        }

    deal["project_description"]        = args.project_description
    deal["information_categories"]     = args.information_categories or "TBD — fill before signing"
    deal["beginning_ci_sharing_date"]  = beginning_date

    context = {
        "tenant": {
            "principal_name":  principal["name"],
            "principal_email": (principal.get("accounts") or [{}])[0].get("address", "TBD"),
        },
        "entity":   entity,
        "deal":     deal,
        "today":    today.strftime("%Y-%m-%d"),
    }
    rendered = render(template_text, context)

    nda_slug = args.slug or f"nda-{slugify(args.counterparty_name)}-{today.year}-{args.direction}"

    print(f"=== compose-nda ({args.direction}) ===")
    print(f"counterparty: {args.counterparty_name}")
    print(f"our entity:   {entity.get('legal_name')} ({args.entity})")
    print(f"slug:         {nda_slug}")
    print(f"effective:    {beginning_date}")
    print(f"resolved:     {len(rendered.resolved)}, unresolved: {len(rendered.unresolved)}")
    if rendered.unresolved:
        print(f"  unresolved: {rendered.unresolved}")

    if args.dry_run:
        print()
        print("--- rendered (first 60 lines) ---")
        for line in rendered.text.splitlines()[:60]:
            print(line)
        emit_telemetry(SCRIPT_NAME, outcome="success", dry_run=True,
                       direction=args.direction, entity=args.entity,
                       counterparty=args.counterparty_name,
                       variables_resolved=len(rendered.resolved),
                       variables_unresolved=len(rendered.unresolved))
        return 0

    vault = Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"]))
    out_dir = vault / "Legal" / "Contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{nda_slug}.md"
    if out_path.exists():
        backup = out_path.with_suffix(f".prev-{int(time.time())}.md")
        shutil.copy2(out_path, backup)
    out_path.write_text(rendered.text)
    print(f"wrote: {out_path}")

    inserted = insert_nda_row(
        nda_slug, deal, entity, args.tenant, our_signatory_name,
        str(out_path.relative_to(vault)),
    )
    if inserted:
        print(f"contracts.db: inserted NDA row '{nda_slug}' (status=DRAFT, direction={args.direction})")

    sweep = "skipped"
    if (entity.get("brand") or {}).get("no_em_dash"):
        result = subprocess.run(
            [str(Path.home() / "Winnie" / "bin" / "voice-sweep.sh"), str(out_path)],
            capture_output=True, text=True, timeout=10,
        )
        sweep = "pass" if result.returncode == 0 else "fail"
        print(f"voice sweep: {sweep}")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   direction=args.direction, entity=args.entity,
                   counterparty=args.counterparty_name,
                   variables_resolved=len(rendered.resolved),
                   variables_unresolved=len(rendered.unresolved),
                   contract_inserted=int(inserted),
                   voice_sweep=sweep,
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
