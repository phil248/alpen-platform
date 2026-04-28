#!/usr/bin/env python3
"""Generate a kickoff deck for a new engagement.

Reads:
  engagements.db        — engagement metadata
  contracts.db          — SOW for fee + payment milestones
  templates/<entity-or-default>/kickoff-deck.md

Writes:
  ${VAULT}/Delivery/Engagements/<id>/kickoff.md

Use case: triggered when an engagement transitions to status='KICKOFF' and
the kickoff date is within 14 days. Provides a template-driven deck for
the kickoff meeting.

Usage:
  compose-kickoff.py --tenant phil-howard --engagement-id <id>
  compose-kickoff.py --tenant phil-howard --engagement-id <id> --dry-run
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
from _template_renderer import render  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "compose-kickoff"
ENGAGEMENTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/engagements.db"))
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def load_template(tenant_id: str, entity_id: str | None) -> tuple[Path, str]:
    name = "kickoff-deck.md"
    candidates = [
        PLATFORM_ROOT / "templates" / (entity_id or "_") / name,
        PLATFORM_ROOT / "templates" / tenant_id / name,
        PLATFORM_ROOT / "templates" / "default" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c, c.read_text()
    sys.exit("error: kickoff-deck template not found")


def load_engagement(eid: str) -> dict | None:
    if not ENGAGEMENTS_DB.is_file():
        return None
    conn = sqlite3.connect(ENGAGEMENTS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM engagement WHERE id = ?", (eid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def load_deliverables(eid: str) -> list[dict]:
    if not ENGAGEMENTS_DB.is_file():
        return []
    conn = sqlite3.connect(ENGAGEMENTS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM engagement_deliverable WHERE engagement_id = ? ORDER BY sequence
    """, (eid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_contract(cid: str) -> dict | None:
    if not CONTRACTS_DB.is_file() or not cid:
        return None
    conn = sqlite3.connect(CONTRACTS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM contract WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--engagement-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = time.time()
    tenant_cfg = load_tenant_cfg(args.tenant)
    eng = load_engagement(args.engagement_id)
    if not eng:
        sys.exit(f"error: engagement {args.engagement_id!r} not found")

    template_path, template_text = load_template(args.tenant, eng.get("entity_id"))
    deliverables = load_deliverables(args.engagement_id)
    contract = load_contract(eng.get("contract_id")) if eng.get("contract_id") else None

    today = datetime.now()
    kickoff_date = eng.get("kickoff_date") or (today + timedelta(days=14)).strftime("%Y-%m-%d")
    end_date = eng.get("planned_end_date") or "TBD"
    midpoint_date = "TBD"
    if eng.get("kickoff_date") and eng.get("planned_end_date"):
        try:
            ks = datetime.fromisoformat(eng["kickoff_date"])
            ke = datetime.fromisoformat(eng["planned_end_date"])
            midpoint = ks + (ke - ks) / 2
            midpoint_date = midpoint.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    principal = next((p for p in tenant_cfg["principals"] if p.get("role") == "ceo"), tenant_cfg["principals"][0])
    partner = next((p for p in tenant_cfg["principals"] if p.get("role") == "partner"), None)
    entity = next((e for e in tenant_cfg["entities"] if e.get("id") == eng.get("entity_id")), tenant_cfg["entities"][0])

    deal = {
        "client_name":           eng.get("client_name") or "TBD",
        "engagement_name":       eng.get("display_name") or args.engagement_id,
        "engagement_one_liner":  f"Tier {eng.get('tier')} engagement to deliver {eng.get('display_name')}",
        "target_outcome":        "TBD — fill from accepted proposal",
        "success_metric":        "TBD",
        "kickoff_purpose":       f"Kick off the {eng.get('display_name')} engagement; align on schedule, working rhythm, and what 'done' looks like.",
        "build_end_week":        "TBD",
        "discovery_end":         "TBD",
        "midpoint_demo":         midpoint_date,
        "final_delivery":        end_date,
        "sow_end_date":          end_date,
        "standup_day":           "Monday",
        "standup_time":          "09:00",
        "standup_duration":      "30 minutes",
        "steering_cadence":      "Bi-weekly Wednesdays",
        "status_report_day":     "Friday",
        "async_channel":         "TBD — Slack channel or shared inbox to be created at kickoff",
        "principal_role":        "Engagement lead",
        "principal_when":        "Full engagement",
        "partner_role":          "Subject-matter contributor",
        "partner_when":          "As scope requires",
        "contributor_3_name":    "TBD",
        "contributor_3_role":    "TBD",
        "contributor_3_when":    "TBD",
        "client_sponsor_name":   eng.get("client_sponsor_name") or "TBD",
        "client_poc_name":       eng.get("client_poc_name") or "TBD",
        "client_team_lead":      "TBD",
        "access_systems":        "TBD",
        "access_target":         "Within 5 business days of kickoff",
        "stakeholder_interview_count": "5-8",
        "client_decision_areas": "TBD",
        "risk_1":                "TBD",
        "risk_1_impact":         "TBD",
        "risk_1_mitigation":     "TBD",
        "risk_2":                "TBD",
        "risk_2_impact":         "TBD",
        "risk_2_mitigation":     "TBD",
        # Deliverables
        "deliverable_1":         deliverables[0]["name"] if len(deliverables) > 0 else "TBD",
        "deliverable_1_criteria": deliverables[0].get("acceptance_criteria") or "TBD" if len(deliverables) > 0 else "TBD",
        "deliverable_2":         deliverables[1]["name"] if len(deliverables) > 1 else "TBD",
        "deliverable_2_criteria": deliverables[1].get("acceptance_criteria") or "TBD" if len(deliverables) > 1 else "TBD",
        "deliverable_3":         deliverables[2]["name"] if len(deliverables) > 2 else "TBD",
        "deliverable_3_criteria": deliverables[2].get("acceptance_criteria") or "TBD" if len(deliverables) > 2 else "TBD",
    }

    context = {
        "tenant": {
            "principal_name":  principal.get("name"),
            "principal_title": principal.get("role", "ceo").upper(),
            "principal_email": (principal.get("accounts") or [{}])[0].get("address", "TBD"),
            "principal_phone": "TBD",
            "partner_name":    (partner or {}).get("name", "TBD"),
            "partner_email":   ((partner or {}).get("accounts") or [{}])[0].get("address", "TBD") if partner else "TBD",
            "escalation_executive": "TBD",
        },
        "entity": entity,
        "principal": principal,
        "deal": deal,
        "today": today.strftime("%Y-%m-%d"),
    }

    rendered = render(template_text, context)
    print(f"=== compose-kickoff ===")
    print(f"engagement: {eng.get('display_name')} ({args.engagement_id})")
    print(f"client:     {eng.get('client_name')}")
    print(f"entity:     {eng.get('entity_id')}")
    print(f"kickoff:    {kickoff_date}")
    print(f"end:        {end_date}")
    print(f"deliverables linked: {len(deliverables)}")
    print(f"resolved:   {len(rendered.resolved)}, unresolved: {len(rendered.unresolved)}")

    if args.dry_run:
        print("\n--- rendered (first 50 lines) ---")
        for line in rendered.text.splitlines()[:50]:
            print(line)
        emit_telemetry(SCRIPT_NAME, outcome="success", dry_run=True,
                       engagement_id=args.engagement_id,
                       deliverables_linked=len(deliverables))
        return 0

    vault = Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"]))
    out_dir = vault / "Delivery" / "Engagements" / args.engagement_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "kickoff.md"
    if out_path.exists():
        backup = out_path.with_suffix(f".prev-{int(time.time())}.md")
        shutil.copy2(out_path, backup)
    out_path.write_text(rendered.text)
    print(f"wrote: {out_path}")

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
                   deliverables_linked=len(deliverables),
                   variables_resolved=len(rendered.resolved),
                   variables_unresolved=len(rendered.unresolved),
                   voice_sweep=sweep,
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
