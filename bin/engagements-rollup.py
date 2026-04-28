#!/usr/bin/env python3
"""Generate a markdown rollup of engagements.db.

Writes ${VAULT}/Delivery/Engagements.md.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
ENGAGEMENTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/engagements.db"))
SCRIPT_NAME = "engagements-rollup"

HEALTH_BADGE = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def fmt_money(amount: int | None) -> str:
    return "—" if amount is None else f"${amount:,}"


def fmt_date(d: str | None) -> str:
    if not d:
        return "TBD"
    return d.split("T")[0]


def render_rollup(conn: sqlite3.Connection, tenant_cfg: dict) -> str:
    today_iso = datetime.now().strftime("%Y-%m-%d")
    out = []
    out.append("---")
    out.append("tags:")
    out.append("  - alpen-platform")
    out.append("  - delivery")
    out.append("  - engagements-rollup")
    out.append(f"generated: {today_iso}")
    out.append(f"tenant: {tenant_cfg['tenant']['id']}")
    out.append("---")
    out.append("")
    out.append("# Engagements (Alpen Platform)")
    out.append("")
    out.append("> **Auto-generated** from `engagements.db`. Edit per-engagement markdown source files; rerun `bin/regenerate-engagements-index.py` to refresh.")
    out.append("")

    # Summary
    cur = conn.execute("""
        SELECT
          COUNT(*) AS active_count,
          SUM(COALESCE(total_value, 0)) AS active_value,
          SUM(CASE WHEN health_color = 'green' THEN 1 ELSE 0 END) AS green,
          SUM(CASE WHEN health_color = 'yellow' THEN 1 ELSE 0 END) AS yellow,
          SUM(CASE WHEN health_color = 'red' THEN 1 ELSE 0 END) AS red
        FROM engagement WHERE status IN ('ACTIVE', 'AT_RISK', 'KICKOFF')
    """)
    s = cur.fetchone()
    out.append("## Portfolio summary")
    out.append("")
    out.append(f"- **Active engagements:** {s[0] or 0}  ({fmt_money(s[1])})")
    out.append(f"- **Health:** {HEALTH_BADGE['green']} {s[2] or 0} green · {HEALTH_BADGE['yellow']} {s[3] or 0} yellow · {HEALTH_BADGE['red']} {s[4] or 0} red")
    out.append("")

    # Active engagements
    active = list(conn.execute("""
        SELECT id, display_name, client_name, tier, principal_owner,
               status, health_score, health_color,
               planned_end_date, days_remaining, total_value
        FROM v_active_engagements
    """))
    out.append(f"## Active engagements ({len(active)})")
    out.append("")
    if active:
        out.append("| Engagement | Client | Tier | Owner | Status | Health | End | Days left | Value |")
        out.append("|------------|--------|------|-------|--------|--------|-----|-----------|-------|")
        for r in active:
            health = f"{HEALTH_BADGE.get(r[7], '⚪')} {r[6] or '?'}/100"
            days = "—" if r[9] is None else f"{int(r[9])}"
            out.append(f"| [[Delivery/Engagements/{r[0]}\\|{r[1]}]] | {r[2]} | T{r[3]} | {r[4]} | {r[5]} | {health} | {fmt_date(r[8])} | {days} | {fmt_money(r[10])} |")
    else:
        out.append("_None._")
    out.append("")

    # At-risk
    at_risk = list(conn.execute("""
        SELECT id, display_name, client_name, health_score, health_color, open_risks
        FROM v_at_risk_engagements
    """))
    out.append(f"## At-risk engagements ({len(at_risk)})")
    out.append("")
    if at_risk:
        out.append("| Engagement | Client | Health | Open risks |")
        out.append("|------------|--------|--------|------------|")
        for r in at_risk:
            out.append(f"| [[Delivery/Engagements/{r[0]}\\|{r[1]}]] | {r[2]} | {HEALTH_BADGE.get(r[4], '⚪')} {r[3] or '?'}/100 | {r[5]} |")
    else:
        out.append("_None._")
    out.append("")

    # Deliverables upcoming
    upcoming = list(conn.execute("""
        SELECT id, engagement_name, deliverable_name, due_date, days_to_due
        FROM v_deliverables_upcoming
    """))
    out.append(f"## Deliverables due in next 14 days ({len(upcoming)})")
    out.append("")
    if upcoming:
        out.append("| Engagement | Deliverable | Due | Days |")
        out.append("|------------|-------------|-----|------|")
        for r in upcoming:
            out.append(f"| {r[1]} | {r[2]} | {fmt_date(r[3])} | {int(r[4])} |")
    else:
        out.append("_None in the next 14 days._")
    out.append("")

    # Status reports overdue
    overdue = list(conn.execute("""
        SELECT id, display_name, client_name, last_status_date, days_since_last
        FROM v_status_report_overdue
    """))
    out.append(f"## Status reports overdue ({len(overdue)})")
    out.append("")
    if overdue:
        out.append("| Engagement | Client | Last status | Days since |")
        out.append("|------------|--------|-------------|------------|")
        for r in overdue:
            last = fmt_date(r[3]) if r[3] else "_never_"
            days = "_n/a_" if r[4] is None else f"{int(r[4])}"
            out.append(f"| [[Delivery/Engagements/{r[0]}\\|{r[1]}]] | {r[2]} | {last} | {days} |")
    else:
        out.append("_All current._")
    out.append("")

    # All engagements by status
    out.append("## By status")
    out.append("")
    for status in ["KICKOFF", "ACTIVE", "AT_RISK", "PAUSED", "CLOSED", "CANCELLED"]:
        rows = list(conn.execute("""
            SELECT id, display_name, client_name, tier, total_value
            FROM engagement WHERE status = ?
            ORDER BY total_value DESC NULLS LAST
        """, (status,)))
        if not rows:
            continue
        out.append(f"### {status.title()} ({len(rows)})")
        out.append("")
        for r in rows:
            out.append(f"- [[Delivery/Engagements/{r[0]}|{r[1]}]] (T{r[3]}, {r[2]}) — {fmt_money(r[4])}")
        out.append("")

    out.append("---")
    out.append(f"_Generated {today_iso} by alpen-platform/bin/engagements-rollup.py_")
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    if not ENGAGEMENTS_DB.is_file():
        sys.exit("error: engagements.db not found; run regenerate-engagements-index.py first")

    cfg_path = PLATFORM_ROOT / "tenants" / args.tenant / "config.yaml"
    with cfg_path.open() as f:
        tenant_cfg = yaml.safe_load(f)

    output = (Path(args.output) if args.output else
              Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"])) / "Delivery" / "Engagements.md")
    output.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    conn = sqlite3.connect(ENGAGEMENTS_DB)
    text = render_rollup(conn, tenant_cfg)
    conn.close()
    output.write_text(text)
    print(f"=== engagements-rollup ===")
    print(f"  wrote: {output} ({len(text)} chars)")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   chars_written=len(text),
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
