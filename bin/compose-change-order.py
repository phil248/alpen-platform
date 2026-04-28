#!/usr/bin/env python3
"""Render an engagement Change Order to amend an executed SOW.

Reads:
  engagements.db        — engagement row + count of existing change orders
  contracts.db          — parent SOW for fee + dates
  templates/<entity-or-default>/change-order-template.md

Writes:
  ${VAULT}/Delivery/Engagements/<eid>/Change-Orders/<n>.md (markdown)
  engagements.db.engagement_change_order row (status=PROPOSED)

Use case: scope, schedule, or fee changes mid-engagement that the SOW's
Section 8 (change-order procedure) requires to be papered before work
proceeds. Status starts PROPOSED; flip to APPROVED once both parties sign.

Usage:
  compose-change-order.py --tenant phil-howard --engagement-id <id> \\
    --description "Add FactSet integration" \\
    --reason "Client requested late in discovery" \\
    --value-delta 15000 --hours-delta 40 --schedule-delta-days 7

  compose-change-order.py --tenant phil-howard --engagement-id <id> \\
    --description "..." --reason "..." \\
    --schedule-delta-days -14   # accelerate by 2 weeks
"""

from __future__ import annotations

import argparse
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
from _regenerator_lib import build_signatory_context, emit_telemetry  # noqa: E402
from _template_renderer import render  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "compose-change-order"
ENGAGEMENTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/engagements.db"))
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def load_template(tenant_id: str, entity_id: str | None) -> tuple[Path, str]:
    name = "change-order-template.md"
    candidates = [
        PLATFORM_ROOT / "templates" / (entity_id or "_") / name,
        PLATFORM_ROOT / "templates" / tenant_id / name,
        PLATFORM_ROOT / "templates" / "default" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c, c.read_text()
    sys.exit("error: change-order-template not found")


def load_engagement(eid: str) -> dict | None:
    if not ENGAGEMENTS_DB.is_file():
        return None
    conn = sqlite3.connect(ENGAGEMENTS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM engagement WHERE id = ?", (eid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def next_change_order_number(eid: str) -> int:
    if not ENGAGEMENTS_DB.is_file():
        return 1
    conn = sqlite3.connect(ENGAGEMENTS_DB)
    cur = conn.execute(
        "SELECT COALESCE(MAX(change_order_number), 0) FROM engagement_change_order "
        "WHERE engagement_id = ?", (eid,),
    ).fetchone()
    conn.close()
    return (cur[0] or 0) + 1


def load_sow(contract_id: str) -> dict | None:
    if not CONTRACTS_DB.is_file() or not contract_id:
        return None
    conn = sqlite3.connect(CONTRACTS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM contract WHERE id = ?", (contract_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_change_order(eid: str, num: int, description: str, scope_delta: str,
                          value_delta: int | None, hours_delta: float | None,
                          schedule_delta_days: int | None,
                          contract_amendment_id: int | None,
                          vault_path: str) -> bool:
    if not ENGAGEMENTS_DB.is_file():
        return False
    conn = sqlite3.connect(ENGAGEMENTS_DB)
    try:
        conn.execute("""
            INSERT INTO engagement_change_order (
              engagement_id, change_order_number, description, scope_delta,
              value_delta, hours_delta, schedule_delta_days,
              proposed_at, status, contract_amendment_id, vault_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), 'PROPOSED', ?, ?)
        """, (eid, num, description, scope_delta, value_delta, hours_delta,
              schedule_delta_days, contract_amendment_id, vault_path))
        conn.commit()
        return True
    except sqlite3.IntegrityError as e:
        print(f"  ! integrity error: {e}", file=sys.stderr)
        return False
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--engagement-id", required=True)
    parser.add_argument("--description", required=True, help="One-line summary of the change")
    parser.add_argument("--reason", required=True, help="Why the change is needed")
    parser.add_argument("--scope-delta", help="Bullet list of scope items (multiline OK)")
    parser.add_argument("--value-delta", type=int, default=0, help="USD; can be negative")
    parser.add_argument("--hours-delta", type=float, default=0.0, help="hours; can be negative")
    parser.add_argument("--schedule-delta-days", type=int, default=0,
                        help="days; can be negative for acceleration")
    parser.add_argument("--effective-date", help="ISO YYYY-MM-DD; defaults to today")
    parser.add_argument("--client-signatory-name")
    parser.add_argument("--client-signatory-title")
    parser.add_argument("--signatory", help="principal id of OUR signer (overrides default)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = time.time()
    tenant_cfg = load_tenant_cfg(args.tenant)
    eng = load_engagement(args.engagement_id)
    if not eng:
        sys.exit(f"error: engagement {args.engagement_id!r} not in engagements.db")

    entity_id = eng.get("entity_id") or "ccg"
    entity = next((e for e in tenant_cfg["entities"] if e.get("id") == entity_id), tenant_cfg["entities"][0])
    sig_ctx = build_signatory_context(tenant_cfg, entity_id, args.signatory)

    sow = load_sow(eng["contract_id"])
    n = next_change_order_number(args.engagement_id)
    today = datetime.now().strftime("%Y-%m-%d")
    effective = args.effective_date or today

    template_path, template_text = load_template(args.tenant, entity_id)

    original_value = (sow or {}).get("total_value") or eng.get("total_value") or 0
    revised_value = original_value + (args.value_delta or 0)

    deal = {
        "change_order_number":         str(n),
        "sow_number":                  (sow or {}).get("id", args.engagement_id),
        "sow_effective_date":          (sow or {}).get("effective_date") or "TBD",
        "contracting_entity":          entity.get("legal_name", "TBD"),
        "client_name":                 eng.get("client_name", "TBD"),
        "change_order_effective_date": effective,
        "change_description":          args.description,
        "change_reason":                args.reason,
        "scope_delta":                  args.scope_delta or f"- {args.description}",
        "milestone_1_name":             "Discovery complete",
        "milestone_1_original":         "TBD",
        "milestone_1_revised":          "TBD",
        "milestone_2_name":             "Mid-sprint demo",
        "milestone_2_original":         "TBD",
        "milestone_2_revised":          "TBD",
        "final_delivery_original":      eng.get("planned_end_date") or "TBD",
        "final_delivery_revised":        "TBD",
        "schedule_delta_days":           str(args.schedule_delta_days),
        "original_value":                f"{original_value:,}",
        "value_delta":                   f"{args.value_delta:,}",
        "revised_value":                 f"{revised_value:,}",
        "hours_delta":                   str(args.hours_delta),
        "payment_terms":                 "Per the SOW payment schedule.",
        "assumption_1":                  "TBD - capture before signature",
        "assumption_2":                  "TBD",
        "client_signatory_name":         args.client_signatory_name or "TBD",
        "client_signatory_title":        args.client_signatory_title or "TBD",
    }

    context = {
        "tenant": {**sig_ctx},
        "entity":   entity,
        "deal":     deal,
        "today":    today,
    }
    rendered = render(template_text, context)

    print(f"=== compose-change-order ===")
    print(f"engagement:  {eng['display_name']} ({args.engagement_id})")
    print(f"sow:         {(sow or {}).get('id', '— (no parent SOW found)')}")
    print(f"change #:    {n}")
    print(f"effective:   {effective}")
    print(f"value delta: ${args.value_delta:,}  ->  revised total: ${revised_value:,}")
    print(f"hours delta: {args.hours_delta}")
    print(f"schedule:    {args.schedule_delta_days:+d} days")
    print(f"resolved:    {len(rendered.resolved)}, unresolved: {len(rendered.unresolved)}")
    if rendered.unresolved:
        print(f"  unresolved: {rendered.unresolved}")

    if args.dry_run:
        print()
        print("--- rendered (first 50 lines) ---")
        for line in rendered.text.splitlines()[:50]:
            print(line)
        emit_telemetry(SCRIPT_NAME, outcome="success", dry_run=True,
                       engagement_id=args.engagement_id, change_order_number=n,
                       value_delta=args.value_delta,
                       schedule_delta_days=args.schedule_delta_days)
        return 0

    vault = Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"]))
    out_dir = vault / "Delivery" / "Engagements" / args.engagement_id / "Change-Orders"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{n:02d}.md"
    if out_path.exists():
        backup = out_path.with_suffix(f".prev-{int(time.time())}.md")
        shutil.copy2(out_path, backup)
    out_path.write_text(rendered.text)
    print(f"wrote: {out_path}")

    inserted = insert_change_order(
        args.engagement_id, n, args.description, args.scope_delta or args.description,
        args.value_delta, args.hours_delta, args.schedule_delta_days,
        contract_amendment_id=None,
        vault_path=str(out_path.relative_to(vault)),
    )
    if inserted:
        print(f"engagements.db: inserted change-order #{n} (status=PROPOSED)")

    sweep = "skipped"
    if (entity.get("brand") or {}).get("no_em_dash"):
        result = subprocess.run(
            [str(Path.home() / "Winnie" / "bin" / "voice-sweep.sh"), str(out_path)],
            capture_output=True, text=True, timeout=10,
        )
        sweep = "pass" if result.returncode == 0 else "fail"
        print(f"voice sweep: {sweep}")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   engagement_id=args.engagement_id,
                   change_order_number=n,
                   value_delta=args.value_delta,
                   hours_delta=args.hours_delta,
                   schedule_delta_days=args.schedule_delta_days,
                   variables_resolved=len(rendered.resolved),
                   variables_unresolved=len(rendered.unresolved),
                   inserted=int(inserted),
                   voice_sweep=sweep,
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
