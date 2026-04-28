#!/usr/bin/env python3
"""Generate a markdown rollup of the leads.db state DB.

Mirrors the existing regenerate-pipeline-rollup.py pattern (CCG-Pipeline.md)
but reads from the platform's leads.db instead of the per-opp markdown
directly. Writes to ${VAULT}/Sales/Pipeline.md.

Usage:
  leads-rollup.py --tenant phil-howard
  leads-rollup.py --tenant phil-howard --output /custom/path.md
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
LEADS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/leads.db"))
SCRIPT_NAME = "leads-rollup"


# Pretty stage names for output
STAGE_DISPLAY = {
    "WON": "Closed - Won",
    "PROPOSED": "Proposed",
    "NEGOTIATING": "Negotiating",
    "SCOPED": "Scoped",
    "DISCOVERED": "Discovered",
    "ENGAGED": "Engaged",
    "QUALIFIED": "Qualified",
    "NEW": "New / Prospect",
    "LOST": "Closed - Lost",
    "DISQUALIFIED": "Disqualified",
}

# Display order: active deals first (highest-stage first), terminal stages last
STAGE_ORDER = [
    "WON", "PROPOSED", "NEGOTIATING", "SCOPED", "DISCOVERED",
    "ENGAGED", "QUALIFIED", "NEW", "LOST", "DISQUALIFIED",
]
ACTIVE_STAGES = {"NEW", "QUALIFIED", "ENGAGED", "DISCOVERED", "SCOPED", "PROPOSED", "NEGOTIATING"}


def fmt_money(amount: int | None) -> str:
    if amount is None:
        return "—"
    return f"${amount:,}"


def fmt_date(d: str | None) -> str:
    if not d:
        return "TBD"
    try:
        # Handle both ISO date and datetime
        dt = datetime.fromisoformat(d.split("T")[0])
        return dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return d


def render_rollup(conn: sqlite3.Connection, tenant_cfg: dict) -> str:
    today_iso = datetime.now().strftime("%Y-%m-%d")
    out = []

    # Frontmatter
    out.append("---")
    out.append("tags:")
    out.append("  - alpen-platform")
    out.append("  - sales")
    out.append("  - leads-rollup")
    out.append(f"generated: {today_iso}")
    out.append(f"tenant: {tenant_cfg['tenant']['id']}")
    out.append("---")
    out.append("")

    out.append("# Pipeline (Alpen Platform)")
    out.append("")
    out.append("> **Auto-generated** by `bin/leads-rollup.py` from `leads.db`. To change a deal, edit its source markdown in `${VAULT}/Sales/Leads/<slug>.md` (or whichever per-tenant source is configured), then run `bin/regenerate-leads-index.py --tenant <id>`.")
    out.append("")

    # Pipeline summary by stage
    out.append("## Summary by stage")
    out.append("")
    out.append("| Stage | Deals | Raw value | Weighted value |")
    out.append("|-------|-------|-----------|----------------|")
    for row in conn.execute("""
        SELECT stage, deal_count, raw_value, weighted_value
        FROM v_pipeline_summary
        ORDER BY CASE stage
            WHEN 'PROPOSED' THEN 1 WHEN 'NEGOTIATING' THEN 2 WHEN 'SCOPED' THEN 3
            WHEN 'DISCOVERED' THEN 4 WHEN 'ENGAGED' THEN 5 WHEN 'QUALIFIED' THEN 6
            WHEN 'NEW' THEN 7 ELSE 99 END
    """):
        out.append(f"| {STAGE_DISPLAY.get(row[0], row[0])} | {row[1]} | {fmt_money(row[2])} | {fmt_money(row[3] or 0)} |")
    out.append("")

    # Overdue actions
    overdue = list(conn.execute("""
        SELECT id, display_name, owner, stage, next_action, next_action_due,
               julianday('now') - julianday(next_action_due) AS days_overdue
        FROM v_overdue_actions
        ORDER BY days_overdue DESC
    """))
    out.append(f"## Overdue actions ({len(overdue)})")
    out.append("")
    if overdue:
        out.append("| Deal | Owner | Stage | Action | Due | Days overdue |")
        out.append("|------|-------|-------|--------|-----|--------------|")
        for r in overdue:
            out.append(f"| [[Sales/Leads/{r[0]}\\|{r[1]}]] | {r[2]} | {STAGE_DISPLAY.get(r[3], r[3])} | {r[4]} | {fmt_date(r[5])} | {int(r[6])} |")
    else:
        out.append("_None — pipeline hygiene clean._")
    out.append("")

    # Stuck deals (>30 days in stage)
    stuck = list(conn.execute("""
        SELECT id, display_name, owner, stage, value_estimate, days_stuck
        FROM v_stuck_deals
        ORDER BY days_stuck DESC
    """))
    out.append(f"## Stuck deals — same stage 30+ days ({len(stuck)})")
    out.append("")
    if stuck:
        out.append("| Deal | Owner | Stage | Value | Days stuck |")
        out.append("|------|-------|-------|-------|------------|")
        for r in stuck:
            out.append(f"| [[Sales/Leads/{r[0]}\\|{r[1]}]] | {r[2]} | {STAGE_DISPLAY.get(r[3], r[3])} | {fmt_money(r[4])} | {int(r[5])} |")
    else:
        out.append("_None — every deal has moved within the last 30 days._")
    out.append("")

    # Single-threaded deals
    st = list(conn.execute("""
        SELECT id, display_name, owner, stage, value_estimate
        FROM v_single_threaded
        ORDER BY value_estimate DESC NULLS LAST
        LIMIT 10
    """))
    out.append(f"## Single-threaded deals (top 10 by value)")
    out.append("")
    if st:
        out.append("| Deal | Owner | Stage | Value |")
        out.append("|------|-------|-------|-------|")
        for r in st:
            out.append(f"| [[Sales/Leads/{r[0]}\\|{r[1]}]] | {r[2]} | {STAGE_DISPLAY.get(r[3], r[3])} | {fmt_money(r[4])} |")
    else:
        out.append("_None — every deal has multiple contacts._")
    out.append("")

    # By-stage breakdown (active stages only)
    out.append("## By stage")
    out.append("")
    for stage in STAGE_ORDER:
        deals = list(conn.execute("""
            SELECT id, display_name, owner, value_estimate, next_action, next_action_due
            FROM lead WHERE stage = ?
            ORDER BY value_estimate DESC NULLS LAST
        """, (stage,)))
        if not deals:
            continue
        out.append(f"### {STAGE_DISPLAY.get(stage, stage)} ({len(deals)})")
        out.append("")
        for d in deals:
            value_str = f" — {fmt_money(d[3])}" if d[3] else ""
            owner_str = f" — {d[2]}" if d[2] else ""
            action_str = ""
            if d[4]:
                action_str = f" (next: {d[4]}"
                if d[5]:
                    action_str += f" — due {fmt_date(d[5])}"
                action_str += ")"
            out.append(f"- [[Sales/Leads/{d[0]}|{d[1]}]]{value_str}{owner_str}{action_str}")
        out.append("")

    out.append("---")
    out.append(f"_Generated {today_iso} by alpen-platform/bin/leads-rollup.py_")
    out.append("")

    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--output", help="Override output path")
    args = parser.parse_args()

    if not LEADS_DB.is_file():
        sys.exit(f"error: leads.db not found; run regenerate-leads-index.py first")

    cfg_path = PLATFORM_ROOT / "tenants" / args.tenant / "config.yaml"
    if not cfg_path.is_file():
        sys.exit(f"error: tenant config not found: {cfg_path}")
    with cfg_path.open() as f:
        tenant_cfg = yaml.safe_load(f)

    output = (Path(args.output) if args.output else
              Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"])) / "Sales" / "Pipeline.md")
    output.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    conn = sqlite3.connect(LEADS_DB)
    conn.row_factory = None
    text = render_rollup(conn, tenant_cfg)
    conn.close()

    output.write_text(text)
    print(f"=== leads-rollup ===")
    print(f"  wrote: {output} ({len(text)} chars)")

    emit_telemetry(
        SCRIPT_NAME, outcome="success",
        chars_written=len(text),
        duration_seconds=round(time.time() - start, 2),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
