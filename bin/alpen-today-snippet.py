#!/usr/bin/env python3
"""Produce an Alpen-Platform-state markdown snippet for daily-standup integration.

Outputs to stdout. Designed to be embedded in
~/Winnie/agents/scheduled/scheduled-daily-standup.md output as section 8c
("Alpen Platform"). Phil can also run it standalone for on-demand state view
— output is byte-identical to what appears in his daily email, eliminating
prompt/email divergence.

Sections (each only emitted if it has content):
  - VoC top — high+ severity unresolved signals (top 5)
  - Pipeline hygiene — stuck deals (>30d in stage), top by value
  - Single-threaded high-value deals
  - Engagement health — at-risk engagements + overdue status reports

Usage:
  alpen-today-snippet.py --tenant phil-howard
  alpen-today-snippet.py --tenant phil-howard --section voc        # one section only
  alpen-today-snippet.py --tenant phil-howard --quiet              # silent if nothing to show
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

LEADS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/leads.db"))
ENGAGEMENTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/engagements.db"))
VOC_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/voc-signals.db"))
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))


def _conn(path: Path) -> sqlite3.Connection | None:
    if not path.is_file():
        return None
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


# ──────────────────────────────────────────────────────────────────────────────
# Section renderers — each returns markdown lines, or [] if nothing to surface
# ──────────────────────────────────────────────────────────────────────────────

def render_voc_top(limit: int = 5) -> list[str]:
    c = _conn(VOC_DB)
    if not c:
        return []
    rows = c.execute("""
        SELECT s.severity, s.signal_type, s.attributed_to_account, s.description,
               t.client_name, t.meeting_date, t.entity_id
        FROM signal s JOIN transcript t ON t.id = s.transcript_id
        WHERE s.resolved_at IS NULL
          AND s.severity IN ('critical', 'high')
        ORDER BY CASE s.severity WHEN 'critical' THEN 1 ELSE 2 END,
                 t.meeting_date DESC
        LIMIT ?
    """, (limit,)).fetchall()
    c.close()
    if not rows:
        return []
    out = ["### VoC — high+ severity, unresolved"]
    out.append("")
    out.append("| Severity | Type | Account | Signal | Source |")
    out.append("|---|---|---|---|---|")
    for r in rows:
        sev_badge = {"critical": "**CRITICAL**", "high": "**high**"}[r["severity"]]
        account = r["attributed_to_account"] or r["client_name"] or "—"
        desc = (r["description"] or "")[:100]
        date = r["meeting_date"] or ""
        entity = r["entity_id"] or ""
        out.append(f"| {sev_badge} | {r['signal_type']} | {account} | {desc} | {date} ({entity}) |")
    out.append("")
    return out


def render_stuck_deals(limit: int = 5, min_value: int = 50000) -> list[str]:
    c = _conn(LEADS_DB)
    if not c:
        return []
    rows = c.execute("""
        SELECT id, display_name, owner, stage, value_estimate, days_stuck
        FROM v_stuck_deals
        WHERE COALESCE(value_estimate, 0) >= ?
        ORDER BY value_estimate DESC NULLS LAST, days_stuck DESC
        LIMIT ?
    """, (min_value, limit)).fetchall()
    c.close()
    if not rows:
        return []
    out = [f"### Pipeline hygiene — high-value deals stuck > 30 days in stage"]
    out.append("")
    out.append("| Deal | Owner | Stage | Value | Days stuck |")
    out.append("|---|---|---|---|---|")
    for r in rows:
        v = f"${r['value_estimate']:,}" if r["value_estimate"] else "—"
        out.append(f"| {r['display_name']} | {r['owner'] or '—'} | {r['stage']} | {v} | {int(r['days_stuck'])} |")
    out.append("")
    return out


def render_single_threaded(limit: int = 5, min_value: int = 100000) -> list[str]:
    c = _conn(LEADS_DB)
    if not c:
        return []
    rows = c.execute("""
        SELECT id, display_name, owner, stage, value_estimate
        FROM v_single_threaded
        WHERE COALESCE(value_estimate, 0) >= ?
        ORDER BY value_estimate DESC NULLS LAST
        LIMIT ?
    """, (min_value, limit)).fetchall()
    c.close()
    if not rows:
        return []
    out = [f"### Pipeline risk — single-threaded deals (≥ ${min_value:,})"]
    out.append("")
    out.append("| Deal | Owner | Stage | Value |")
    out.append("|---|---|---|---|")
    for r in rows:
        v = f"${r['value_estimate']:,}" if r["value_estimate"] else "—"
        out.append(f"| {r['display_name']} | {r['owner'] or '—'} | {r['stage']} | {v} |")
    out.append("")
    return out


def render_at_risk_engagements() -> list[str]:
    c = _conn(ENGAGEMENTS_DB)
    if not c:
        return []
    rows = c.execute("""
        SELECT id, display_name, client_name, health_score, health_color, open_risks
        FROM v_at_risk_engagements
    """).fetchall()
    c.close()
    if not rows:
        return []
    badge = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
    out = ["### At-risk engagements"]
    out.append("")
    out.append("| Engagement | Client | Health | Open risks |")
    out.append("|---|---|---|---|")
    for r in rows:
        health = f"{badge.get(r['health_color'], '⚪')} {r['health_score'] or '?'}/100"
        out.append(f"| {r['display_name']} | {r['client_name']} | {health} | {r['open_risks']} |")
    out.append("")
    return out


def render_status_overdue() -> list[str]:
    c = _conn(ENGAGEMENTS_DB)
    if not c:
        return []
    rows = c.execute("""
        SELECT id, display_name, client_name, last_status_date, days_since_last
        FROM v_status_report_overdue
    """).fetchall()
    c.close()
    if not rows:
        return []
    out = ["### Status reports overdue"]
    out.append("")
    out.append("| Engagement | Client | Last status | Days since |")
    out.append("|---|---|---|---|")
    for r in rows:
        last = r["last_status_date"] or "_never_"
        days = "n/a" if r["days_since_last"] is None else f"{int(r['days_since_last'])}"
        out.append(f"| {r['display_name']} | {r['client_name']} | {last} | {days} |")
    out.append("")
    return out


def render_payments_outstanding() -> list[str]:
    c = _conn(CONTRACTS_DB)
    if not c:
        return []
    rows = c.execute("""
        SELECT id, contract_id, contract_name, milestone, amount,
               due_date, payment_status
        FROM v_payments_outstanding
        ORDER BY due_date ASC NULLS LAST
    """).fetchall()
    c.close()
    if not rows:
        return []
    out = ["### Payments outstanding"]
    out.append("")
    out.append("| Contract | Milestone | Amount | Due | Status |")
    out.append("|---|---|---|---|---|")
    badge = {
        "past_due_uninvoiced": "🔴 past due (uninvoiced)",
        "invoiced_unpaid":      "🟡 invoiced, unpaid",
        "pending":              "pending",
    }
    for r in rows:
        amt = f"${r['amount']:,}" if r["amount"] else "—"
        due = r["due_date"] or "—"
        status = badge.get(r["payment_status"], r["payment_status"])
        out.append(f"| {r['contract_name']} | {r['milestone']} | {amt} | {due} | {status} |")
    out.append("")
    return out


SECTIONS = {
    "voc":              ("VoC top", render_voc_top),
    "stuck":            ("Pipeline hygiene — stuck deals", render_stuck_deals),
    "single_threaded":  ("Pipeline risk — single-threaded", render_single_threaded),
    "at_risk":          ("At-risk engagements", render_at_risk_engagements),
    "status_overdue":   ("Status reports overdue", render_status_overdue),
    "payments":         ("Payments outstanding", render_payments_outstanding),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, help="(reserved; future-proof for multi-tenant)")
    parser.add_argument("--section", choices=list(SECTIONS.keys()), help="render one section only")
    parser.add_argument("--quiet", action="store_true", help="emit nothing if all sections are empty")
    parser.add_argument("--no-header", action="store_true", help="omit the parent ## 8c heading")
    args = parser.parse_args()

    out_lines: list[str] = []

    if args.section:
        out_lines.extend(SECTIONS[args.section][1]())
    else:
        for name, (label, fn) in SECTIONS.items():
            out_lines.extend(fn())

    if not out_lines:
        if args.quiet:
            return 0
        # Minimal placeholder when everything is clean
        if not args.no_header:
            print("## 8c. Alpen Platform")
            print()
        print("_All clean — no high-severity VoC signals, no stuck high-value deals, no at-risk engagements, no overdue status reports, no outstanding payments._")
        return 0

    if not args.no_header and not args.section:
        print("## 8c. Alpen Platform")
        print()
        print("_Pulled from `~/.local/state/alpen/sqlite/{voc-signals,leads,engagements,contracts}.db`. Source-of-truth markdown lives in `${VAULT}/Plaud-Recordings/`, `Cognitive-Capital-Group/Opportunities/`, and `Legal/Contracts/`. Refreshed daily at 06:15 by `alpen-regenerate-all.sh`._")
        print()

    for line in out_lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
