#!/usr/bin/env python3
"""Generate a Quarterly Business Review deck for an active engagement.

Reads:
  engagements.db                    — engagement + status_report + risk + change_order rows
  voc-signals.db                    — VoC signals attributed to the client
  templates/<entity-or-default>/qbr-deck.md

Writes:
  ${VAULT}/CS/QBRs/<engagement-id>-<quarter>.md

Per the qbr-prep SKILL contract.

Usage:
  compose-qbr.py --tenant phil-howard --engagement-id <id>
  compose-qbr.py --tenant phil-howard --engagement-id <id> --quarter "Q2 2026"
  compose-qbr.py --tenant phil-howard --engagement-id <id> --dry-run
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
SCRIPT_NAME = "compose-qbr"
ENGAGEMENTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/engagements.db"))
VOC_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/voc-signals.db"))


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def load_template(tenant_id: str, entity_id: str | None) -> tuple[Path, str]:
    name = "qbr-deck.md"
    candidates = [
        PLATFORM_ROOT / "templates" / (entity_id or "_") / name,
        PLATFORM_ROOT / "templates" / tenant_id / name,
        PLATFORM_ROOT / "templates" / "default" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c, c.read_text()
    sys.exit(f"error: qbr-deck template not found")


def load_engagement(engagement_id: str) -> dict | None:
    if not ENGAGEMENTS_DB.is_file():
        return None
    conn = sqlite3.connect(ENGAGEMENTS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM engagement WHERE id = ?", (engagement_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def quarter_bounds(spec: str | None) -> tuple[str, str, str]:
    """Returns (label, start_iso, end_iso). spec is 'Q2 2026' or None for current."""
    if spec:
        try:
            q, year = spec.upper().split()
            qn = int(q.removeprefix("Q"))
            year = int(year)
        except (ValueError, AttributeError):
            sys.exit(f"error: --quarter must be 'Q1 2026' / 'Q2 2026' / etc., got {spec!r}")
    else:
        now = datetime.now()
        qn = (now.month - 1) // 3 + 1
        year = now.year
    start_month = (qn - 1) * 3 + 1
    end_month = qn * 3
    start = datetime(year, start_month, 1)
    if end_month == 12:
        end = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = datetime(year, end_month + 1, 1) - timedelta(days=1)
    return f"Q{qn} {year}", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def collect_quarter_data(engagement_id: str, client_name: str | None,
                         q_start: str, q_end: str) -> dict:
    """Pull all the data the qbr-deck template variables need."""
    conn = sqlite3.connect(ENGAGEMENTS_DB)
    conn.row_factory = sqlite3.Row

    status_reports = list(conn.execute("""
        SELECT * FROM engagement_status_report
        WHERE engagement_id = ? AND week_start_date BETWEEN ? AND ?
        ORDER BY week_start_date DESC
    """, (engagement_id, q_start, q_end)))

    deliverables_accepted = list(conn.execute("""
        SELECT name, accepted_at FROM engagement_deliverable
        WHERE engagement_id = ? AND status = 'ACCEPTED'
          AND accepted_at BETWEEN ? AND ?
        ORDER BY accepted_at DESC
    """, (engagement_id, q_start, q_end)))

    deliverables_in_progress = list(conn.execute("""
        SELECT name, status, due_date FROM engagement_deliverable
        WHERE engagement_id = ? AND status NOT IN ('ACCEPTED', 'REJECTED')
        ORDER BY due_date NULLS LAST
    """, (engagement_id,)))

    risks_open = list(conn.execute("""
        SELECT description, severity FROM engagement_risk
        WHERE engagement_id = ? AND status = 'OPEN'
        ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                               WHEN 'medium' THEN 3 ELSE 4 END
        LIMIT 5
    """, (engagement_id,)))

    change_orders = list(conn.execute("""
        SELECT description, value_delta, status FROM engagement_change_order
        WHERE engagement_id = ? AND date(proposed_at) BETWEEN ? AND ?
    """, (engagement_id, q_start, q_end)))

    conn.close()

    # VoC signals scoped to this client + quarter
    voc_signals = []
    if VOC_DB.is_file() and client_name:
        vc = sqlite3.connect(VOC_DB)
        vc.row_factory = sqlite3.Row
        voc_signals = [dict(r) for r in vc.execute("""
            SELECT s.signal_type, s.severity, s.description, s.attributed_to_account,
                   t.meeting_date
            FROM signal s JOIN transcript t ON t.id = s.transcript_id
            WHERE (s.attributed_to_account = ? OR t.client_name = ?)
              AND t.meeting_date BETWEEN ? AND ?
              AND s.resolved_at IS NULL
            ORDER BY t.meeting_date DESC
        """, (client_name, client_name, q_start, q_end))]
        vc.close()

    return {
        "status_reports": [dict(r) for r in status_reports],
        "deliverables_accepted": [dict(r) for r in deliverables_accepted],
        "deliverables_in_progress": [dict(r) for r in deliverables_in_progress],
        "risks_open": [dict(r) for r in risks_open],
        "change_orders": [dict(r) for r in change_orders],
        "voc_signals": voc_signals,
    }


def build_quarter_context(eng: dict, q_label: str, q_start: str, q_end: str,
                           data: dict) -> dict:
    """Compose the {{quarter.*}} and {{next_quarter.*}} variables for the template."""
    voc = data["voc_signals"]
    voc_by_type: dict[str, int] = {}
    for s in voc:
        t = s["signal_type"]
        voc_by_type[t] = voc_by_type.get(t, 0) + 1

    expansion_signals = [s for s in voc if s["signal_type"] in ("expansion", "commitment", "ask")]
    objection_signals = [s for s in voc if s["signal_type"] in ("objection", "expansion_blocker", "competitive")]
    churn_signals = [s for s in voc if s["signal_type"] == "churn_risk"]
    feedback_signals = [s for s in voc if s["signal_type"] == "feedback"]

    # Last status-report's tldr is a quick summary of where we ended the quarter
    last_tldr = data["status_reports"][0]["tldr"] if data["status_reports"] else "TBD — no status reports for this quarter"

    quarter = {
        "tldr": last_tldr,
        "deliverables_count": len(data["deliverables_accepted"]),
        "deliverables_in_progress": len(data["deliverables_in_progress"]),
        "objective_1": data["deliverables_accepted"][0]["name"] if len(data["deliverables_accepted"]) > 0 else "TBD",
        "objective_2": data["deliverables_accepted"][1]["name"] if len(data["deliverables_accepted"]) > 1 else "TBD",
        "objective_3": data["deliverables_accepted"][2]["name"] if len(data["deliverables_accepted"]) > 2 else "TBD",
        "objective_1_status": "Accepted" if len(data["deliverables_accepted"]) > 0 else "TBD",
        "objective_2_status": "Accepted" if len(data["deliverables_accepted"]) > 1 else "TBD",
        "objective_3_status": "Accepted" if len(data["deliverables_accepted"]) > 2 else "TBD",
        "objective_1_outcome": "TBD",
        "objective_2_outcome": "TBD",
        "objective_3_outcome": "TBD",
        "metric_1_name": "TBD", "metric_1_prev": "TBD", "metric_1_curr": "TBD", "metric_1_change": "TBD",
        "metric_2_name": "TBD", "metric_2_prev": "TBD", "metric_2_curr": "TBD", "metric_2_change": "TBD",
        "metric_3_name": "TBD", "metric_3_prev": "TBD", "metric_3_curr": "TBD", "metric_3_change": "TBD",
        "worked_1": data["deliverables_accepted"][0]["name"] if data["deliverables_accepted"] else "TBD",
        "worked_2": data["deliverables_accepted"][1]["name"] if len(data["deliverables_accepted"]) > 1 else "TBD",
        "worked_3": "TBD",
        "didnt_work_1": data["risks_open"][0]["description"] if data["risks_open"] else "TBD",
        "didnt_work_1_cause": "TBD — review with team before sending",
        "didnt_work_2": "TBD",
        "didnt_work_2_cause": "TBD",
        "voc_expansion_count": len(expansion_signals),
        "voc_objection_count": len(objection_signals),
        "voc_churn_count": len(churn_signals),
        "voc_theme_1": expansion_signals[0]["description"][:80] if expansion_signals else "TBD",
        "voc_theme_2": objection_signals[0]["description"][:80] if objection_signals else "TBD",
        "voc_theme_3": feedback_signals[0]["description"][:80] if feedback_signals else "TBD",
        "fees_spent": eng.get("total_value", 0),
        "fees_remaining": 0,
        "fees_notes": "TBD",
        "travel_spent": 0,
        "travel_notes": "TBD",
    }
    next_quarter = {
        "objective_1": "TBD — define with team during QBR review",
        "objective_2": "TBD",
        "objective_3": "TBD",
        "action_1": expansion_signals[0]["description"][:80] if expansion_signals else "TBD",
        "action_1_owner": eng.get("principal_owner", "TBD"),
        "action_1_why": "from VoC expansion signal" if expansion_signals else "TBD",
        "action_2": data["risks_open"][0]["description"][:80] if data["risks_open"] else "TBD",
        "action_2_owner": eng.get("principal_owner", "TBD"),
        "action_2_why": "from open engagement risk" if data["risks_open"] else "TBD",
        "action_3": "TBD",
        "action_3_owner": "TBD",
        "action_3_why": "TBD",
    }
    return {"quarter": quarter, "next_quarter": next_quarter}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--engagement-id", required=True)
    parser.add_argument("--quarter", help="'Q2 2026'; defaults to current quarter")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = time.time()
    tenant_cfg = load_tenant_cfg(args.tenant)
    eng = load_engagement(args.engagement_id)
    if not eng:
        sys.exit(f"error: engagement {args.engagement_id!r} not found in engagements.db")

    template_path, template_text = load_template(args.tenant, eng.get("entity_id"))
    q_label, q_start, q_end = quarter_bounds(args.quarter)
    data = collect_quarter_data(args.engagement_id, eng.get("client_name"), q_start, q_end)
    qctx = build_quarter_context(eng, q_label, q_start, q_end, data)

    deal_ctx = {
        "client_name": eng.get("client_name"),
        "engagement_summary": eng.get("display_name"),
        "tier_name": f"Tier {eng.get('tier')}",
        "health_score": eng.get("health_score") or "—",
        "ask_1": "TBD", "ask_1_why": "TBD", "ask_1_due": "TBD",
        "ask_2": "TBD", "ask_2_why": "TBD", "ask_2_due": "TBD",
        "expansion_1": qctx["next_quarter"]["action_1"],
        "expansion_2": "TBD",
        "renewal_date": eng.get("planned_end_date") or "TBD",
        "renewal_recommendation": "TBD",
    }

    principal = next((p for p in tenant_cfg["principals"] if p.get("role") == "ceo"), tenant_cfg["principals"][0])
    partner = next((p for p in tenant_cfg["principals"] if p.get("role") == "partner"), None)
    entity = next((e for e in tenant_cfg["entities"] if e.get("id") == eng.get("entity_id")), tenant_cfg["entities"][0])

    context = {
        "tenant": {
            "principal_name": principal.get("name"),
            "principal_email": (principal.get("accounts") or [{}])[0].get("address", "TBD"),
            "partner_name": partner.get("name") if partner else "TBD",
            "partner_email": ((partner or {}).get("accounts") or [{}])[0].get("address", "TBD") if partner else "TBD",
        },
        "entity": entity,
        "deal": deal_ctx,
        "today": datetime.now().strftime("%Y-%m-%d"),
        "quarter_start": q_start,
        "quarter_end": q_end,
        **qctx,
    }
    # Override the literal {{quarter}} variable used in title slide
    rendered_text = template_text.replace("{{quarter}}", q_label)
    rendered = render(rendered_text, context)

    print(f"=== compose-qbr ===")
    print(f"engagement: {eng.get('display_name')} ({args.engagement_id})")
    print(f"quarter:    {q_label} ({q_start} to {q_end})")
    print(f"data:       {len(data['status_reports'])} status reports, "
          f"{len(data['deliverables_accepted'])} deliverables accepted, "
          f"{len(data['voc_signals'])} VoC signals, "
          f"{len(data['risks_open'])} open risks")
    print(f"resolved:   {len(rendered.resolved)}, unresolved: {len(rendered.unresolved)}")

    if args.dry_run:
        print("\n--- rendered (first 60 lines) ---")
        for line in rendered.text.splitlines()[:60]:
            print(line)
        print("--- end preview ---")
        emit_telemetry(SCRIPT_NAME, outcome="success", dry_run=True,
                       engagement_id=args.engagement_id,
                       quarter=q_label,
                       voc_signals=len(data["voc_signals"]))
        return 0

    vault = Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"]))
    out_dir = vault / "CS" / "QBRs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.engagement_id}-{q_label.replace(' ', '-')}.md"
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
                   quarter=q_label,
                   voc_signals=len(data["voc_signals"]),
                   variables_resolved=len(rendered.resolved),
                   variables_unresolved=len(rendered.unresolved),
                   voice_sweep=sweep,
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
