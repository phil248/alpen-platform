#!/usr/bin/env python3
"""Generate weekly status reports for active engagements.

Reads engagements.db, finds engagements in (ACTIVE, AT_RISK, KICKOFF), and
renders templates/default/status-report.md per engagement to
${VAULT}/Delivery/Engagements/<id>/Status-Reports/YYYY-MM-DD.md.

Persists an engagement_status_report row per generated report.

Usage:
  compose-status-report.py --tenant phil-howard
  compose-status-report.py --tenant phil-howard --engagement-id acme-pharma-2026q2
  compose-status-report.py --tenant phil-howard --week-start 2026-04-21
"""

from __future__ import annotations

import argparse
import os
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
SCRIPT_NAME = "compose-status-report"
ENGAGEMENTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/engagements.db"))


def load_tenant_config(tenant_id: str) -> dict:
    path = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with path.open() as f:
        return yaml.safe_load(f) or {}


def load_template(tenant_id: str, entity_id: str | None) -> tuple[Path, str]:
    name = "status-report.md"
    candidates = [
        PLATFORM_ROOT / "templates" / (entity_id or "_") / name,
        PLATFORM_ROOT / "templates" / tenant_id / name,
        PLATFORM_ROOT / "templates" / "default" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c, c.read_text()
    sys.exit("error: status-report template not found")


def find_engagements(conn: sqlite3.Connection, engagement_id: str | None) -> list[dict]:
    sql = "SELECT * FROM engagement WHERE status IN ('ACTIVE', 'AT_RISK', 'KICKOFF')"
    params = ()
    if engagement_id:
        sql = "SELECT * FROM engagement WHERE id = ?"
        params = (engagement_id,)
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params)]


def collect_week_data(conn: sqlite3.Connection, engagement_id: str, week_start: datetime) -> dict:
    """Pull the past-week activity for an engagement."""
    week_end = week_start + timedelta(days=7)
    week_start_str = week_start.strftime("%Y-%m-%d")
    week_end_str = week_end.strftime("%Y-%m-%d")

    deliverables = list(conn.execute("""
        SELECT name, status, due_date, accepted_at, delivered_at
        FROM engagement_deliverable
        WHERE engagement_id = ?
        ORDER BY sequence
    """, (engagement_id,)))

    risks = list(conn.execute("""
        SELECT description, severity, owner, mitigation
        FROM engagement_risk
        WHERE engagement_id = ? AND status = 'OPEN'
        ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END
        LIMIT 2
    """, (engagement_id,)))

    change_orders = list(conn.execute("""
        SELECT description, status FROM engagement_change_order
        WHERE engagement_id = ? AND date(proposed_at) BETWEEN ? AND ?
    """, (engagement_id, week_start_str, week_end_str)))

    # In-flight: deliverables not yet delivered/accepted
    in_flight = [d for d in deliverables if d[1] in ("PLANNED", "IN_PROGRESS")][:2]
    done_this_week = [
        d for d in deliverables
        if d[1] in ("DELIVERED", "ACCEPTED") and (d[3] or d[4]) and
        (d[3] or d[4]) >= week_start_str
    ][:3]

    return {
        "deliverables": deliverables,
        "in_flight": in_flight,
        "done_this_week": done_this_week,
        "risks": risks,
        "change_orders": change_orders,
    }


def synthesize_week(eng: dict, week_data: dict) -> dict:
    """Heuristic fill for {{week.*}} variables. A real implementation
    would invoke an LLM; this v0.1 produces structured stubs for the user
    to fill in / review."""
    done = week_data["done_this_week"]
    in_flight = week_data["in_flight"]
    risks = week_data["risks"]

    if done:
        tldr = f"{len(done)} deliverable(s) accepted; {eng.get('status')}."
    elif risks:
        tldr = f"{len(risks)} open risk(s); next milestone in {eng.get('planned_end_date') or 'TBD'}."
    else:
        tldr = f"On track. Next milestone {eng.get('planned_end_date') or 'TBD'}."

    return {
        "tldr": tldr,
        "done_1": done[0][0] if len(done) > 0 else "TBD",
        "done_2": done[1][0] if len(done) > 1 else "TBD",
        "done_3": done[2][0] if len(done) > 2 else "TBD",
        "in_flight_1": in_flight[0][0] if len(in_flight) > 0 else "TBD",
        "in_flight_1_status": in_flight[0][1] if len(in_flight) > 0 else "TBD",
        "in_flight_2": in_flight[1][0] if len(in_flight) > 1 else "TBD",
        "in_flight_2_status": in_flight[1][1] if len(in_flight) > 1 else "TBD",
        "next_1": "TBD", "next_2": "TBD", "next_3": "TBD",
        "risk_1": risks[0][0] if len(risks) > 0 else "—",
        "risk_1_sev": risks[0][1] if len(risks) > 0 else "—",
        "risk_1_owner": risks[0][2] if len(risks) > 0 else "—",
        "risk_1_mitigation": risks[0][3] if len(risks) > 0 else "—",
        "risk_2": risks[1][0] if len(risks) > 1 else "—",
        "risk_2_sev": risks[1][1] if len(risks) > 1 else "—",
        "risk_2_owner": risks[1][2] if len(risks) > 1 else "—",
        "risk_2_mitigation": risks[1][3] if len(risks) > 1 else "—",
        "ask_1": "TBD",
        "ask_1_due": "TBD",
        "ask_2": "TBD",
        "ask_2_due": "TBD",
        "hours_used": 0,
    }


def persist_status_row(conn: sqlite3.Connection, eng: dict, week_start: datetime,
                       synth: dict, vault_path: str) -> bool:
    try:
        conn.execute("""
            INSERT INTO engagement_status_report
              (engagement_id, week_start_date, health_score, health_color, hours_used_week,
               hours_used_total, budget_status, tldr, vault_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(engagement_id, week_start_date) DO UPDATE SET
              tldr=excluded.tldr,
              vault_path=excluded.vault_path,
              health_score=COALESCE(excluded.health_score, engagement_status_report.health_score)
        """, (
            eng["id"], week_start.strftime("%Y-%m-%d"),
            eng.get("health_score"), eng.get("health_color"),
            synth.get("hours_used", 0),
            None,  # hours_used_total — not tracked yet
            None,  # budget_status — not tracked yet
            synth["tldr"],
            vault_path,
        ))
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"  ! status row persist failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--engagement-id")
    parser.add_argument("--week-start", help="ISO date; defaults to most recent Monday")
    args = parser.parse_args()

    if not ENGAGEMENTS_DB.is_file():
        sys.exit("error: engagements.db not found; run regenerate-engagements-index first")

    tenant_cfg = load_tenant_config(args.tenant)
    today = datetime.now()
    if args.week_start:
        week_start = datetime.fromisoformat(args.week_start)
    else:
        # Most recent Monday
        week_start = today - timedelta(days=today.weekday())

    start = time.time()
    conn = sqlite3.connect(ENGAGEMENTS_DB)
    engs = find_engagements(conn, args.engagement_id)
    print(f"=== compose-status-report (week of {week_start.strftime('%Y-%m-%d')}) ===")
    print(f"engagements: {len(engs)}")
    if not engs:
        emit_telemetry(SCRIPT_NAME, outcome="success",
                       engagements_reported=0, reports_written=0,
                       duration_seconds=round(time.time() - start, 2))
        return 0

    template_path, template_text = load_template(args.tenant, None)
    vault = Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"]))
    written = 0

    for eng in engs:
        week_data = collect_week_data(conn, eng["id"], week_start)
        synth = synthesize_week(eng, week_data)
        deal_ctx = {
            "engagement_name":  eng.get("display_name"),
            "client_poc_name":  eng.get("client_poc_name") or "TBD",
            "client_sponsor_name": eng.get("client_sponsor_name") or "TBD",
            "health_score":     eng.get("health_score") or "—",
            "health_color":     eng.get("health_color") or "—",
            "sow_end_date":     eng.get("planned_end_date") or "TBD",
            "weeks_remaining":  "TBD",
            "billed_to_date":   0,
            "value":            eng.get("total_value") or 0,
            "hours_total":      0,
            "hours_budget":     eng.get("hours_budget") or 0,
            "budget_status":    "TBD",
        }
        milestone_ctx = {
            "last_completed":      "TBD",
            "last_completed_date": "TBD",
            "next":                "TBD",
            "next_date":           eng.get("planned_end_date") or "TBD",
        }
        context = {
            "tenant": {
                "principal_name":  next((p["name"] for p in tenant_cfg["principals"] if p.get("role") == "ceo"), "TBD"),
                "principal_email": "TBD",
            },
            "entity": next((e for e in tenant_cfg["entities"] if e.get("id") == eng.get("entity_id")), {}),
            "deal":      deal_ctx,
            "week":      synth,
            "milestone": milestone_ctx,
            "today":     today.strftime("%Y-%m-%d"),
            "week_start_date": week_start.strftime("%Y-%m-%d"),
        }
        rendered = render(template_text, context)
        out_dir = vault / "Delivery" / "Engagements" / eng["id"] / "Status-Reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{week_start.strftime('%Y-%m-%d')}.md"
        out_path.write_text(rendered.text)
        rel = str(out_path.relative_to(vault))
        if persist_status_row(conn, eng, week_start, synth, rel):
            written += 1
            print(f"  ✓ {eng['id']} ({eng.get('health_color', '—')}) → {out_path.name}")

    conn.close()

    health_red = sum(1 for e in engs if e.get("health_color") == "red")
    health_yellow = sum(1 for e in engs if e.get("health_color") == "yellow")
    health_green = sum(1 for e in engs if e.get("health_color") == "green")

    print(f"\n{written} report(s) written  (red={health_red}, yellow={health_yellow}, green={health_green})")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   engagements_reported=len(engs), reports_written=written,
                   health_red=health_red, health_yellow=health_yellow, health_green=health_green,
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
