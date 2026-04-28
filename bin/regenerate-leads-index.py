#!/usr/bin/env python3
"""Regenerate leads.db from per-lead markdown files.

Source:  ${VAULT}/Sales/Leads/<slug>.md  (per tenant; configurable)
Target:  ~/.local/state/alpen/sqlite/leads.db

Per record, reads frontmatter (id, name, stage, value, owner, etc.) and the
## History section (parsed into lead_history rows).

Usage:
  regenerate-leads-index.py --tenant phil-howard
  regenerate-leads-index.py --tenant phil-howard --source-dir <override>
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import (  # noqa: E402
    Run, coerce_date, coerce_int, coerce_str, find_records, init_db,
    parse_money, parse_money_range,
)

SCRIPT_NAME = "regenerate-leads-index"

HISTORY_HEADING_RE = re.compile(r"^##\s+History", re.MULTILINE)
HISTORY_ENTRY_RE = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\s*[—-]\s*(.+)$", re.MULTILINE)
STAGE_TRANSITION_RE = re.compile(
    r"(?:moved\s+)?(?:from\s+)?(\w+(?:\s+\w+)*)\s*(?:→|->)\s*(\w+(?:\s+\w+)*)",
    re.IGNORECASE,
)


def stage_normalize(stage: str | None) -> str:
    """Map various stage spellings to canonical leads.db CHECK values.
    Per CCG opportunity-review pattern, accepts 'Prospect', 'In Conversation',
    'Closed - Won', 'Lost'."""
    if not stage:
        return "NEW"
    s = stage.strip().lower()
    mapping = {
        "new": "NEW",
        "prospect": "NEW",
        "qualified": "QUALIFIED",
        "engaged": "ENGAGED",
        "in conversation": "ENGAGED",
        "discovered": "DISCOVERED",
        "discovery": "DISCOVERED",
        "scoped": "SCOPED",
        "scoping": "SCOPED",
        "proposed": "PROPOSED",
        "proposal sent": "PROPOSED",
        "negotiating": "NEGOTIATING",
        "negotiation": "NEGOTIATING",
        "won": "WON",
        "closed - won": "WON",
        "closed-won": "WON",
        "lost": "LOST",
        "closed - lost": "LOST",
        "closed-lost": "LOST",
        "disqualified": "DISQUALIFIED",
    }
    return mapping.get(s, "NEW")


def parse_history(body: str, slug: str) -> list[tuple[str, str, str | None, str | None, str]]:
    """Return list of (occurred_at, event_type, from_stage, to_stage, description)."""
    out = []
    h_match = HISTORY_HEADING_RE.search(body)
    if not h_match:
        return out
    history_block = body[h_match.end():]
    entries = list(HISTORY_ENTRY_RE.finditer(history_block))
    for i, entry in enumerate(entries):
        date = entry.group(1)
        source_label = entry.group(2).strip()
        # Body of this entry = text until next entry or end
        end = entries[i + 1].start() if i + 1 < len(entries) else len(history_block)
        entry_body = history_block[entry.end():end].strip()
        # Try to detect stage transition in this entry
        from_stage, to_stage, event_type = None, None, "note"
        for line in entry_body.splitlines():
            t = STAGE_TRANSITION_RE.search(line)
            if t:
                from_stage = stage_normalize(t.group(1))
                to_stage = stage_normalize(t.group(2))
                event_type = "stage_change"
                break
        # Description = first non-empty line of entry body, or the source label
        desc = source_label
        for line in entry_body.splitlines():
            line = line.strip().lstrip("- ").strip()
            if line:
                desc = line[:240]
                break
        out.append((f"{date} 00:00:00", event_type, from_stage, to_stage, desc))
    return out


def insert_lead(conn: sqlite3.Connection, rec, tenant_id: str, source_dir: Path) -> bool:
    fm = rec.fm
    value_estimate = parse_money(fm.get("value"))
    value_low, value_high = parse_money_range(fm.get("value"))
    # If a single value, value_low/high mirror it; that's fine
    stage = stage_normalize(fm.get("stage"))
    vault_path = str(rec.path.relative_to(source_dir.parent.parent)) if source_dir.parent.parent in rec.path.parents else str(rec.path)
    try:
        conn.execute("""
            INSERT INTO lead (
              id, tenant_id, entity_id, display_name, company_name,
              primary_contact, contact_email, source, source_detail, stage,
              tier, value_estimate, value_low, value_high, probability,
              owner, next_action, next_action_due, next_action_owner,
              stage_entered_date, vault_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rec.slug,
            tenant_id,
            coerce_str(fm.get("entity_id")) or "ccg",
            coerce_str(fm.get("name")) or rec.slug,
            coerce_str(fm.get("company")),
            coerce_str(fm.get("contacts")[0]) if isinstance(fm.get("contacts"), list) and fm.get("contacts") else None,
            coerce_str(fm.get("contact_email")),
            coerce_str(fm.get("source")) or "unknown",
            coerce_str(fm.get("source_detail")),
            stage,
            coerce_int(fm.get("tier")),
            value_estimate,
            value_low,
            value_high,
            None,  # probability — not in current per-opp schema
            coerce_str(fm.get("owner")) or "unknown",
            coerce_str(fm.get("next_action")),
            coerce_date(fm.get("next_action_due")),
            coerce_str(fm.get("next_action_owner")),
            coerce_date(fm.get("stage_entered_date")) or "2026-01-01",
            vault_path,
        ))
    except sqlite3.IntegrityError as e:
        print(f"  ! integrity error inserting {rec.slug}: {e}", file=sys.stderr)
        return False
    # History
    for occurred_at, event_type, from_stage, to_stage, description in parse_history(rec.body, rec.slug):
        conn.execute("""
            INSERT INTO lead_history (lead_id, occurred_at, source, event_type, from_stage, to_stage, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (rec.slug, occurred_at, "markdown", event_type, from_stage, to_stage, description))
    # Contacts (if multiple in frontmatter list)
    contacts = fm.get("contacts")
    if isinstance(contacts, list):
        for name in contacts:
            if not name:
                continue
            conn.execute("""
                INSERT INTO lead_contact (lead_id, name) VALUES (?, ?)
            """, (rec.slug, str(name)))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument(
        "--source-dir",
        help="Override default source directory (default: ${VAULT}/Sales/Leads or "
             "tenant-specific equivalent)",
    )
    args = parser.parse_args()

    vault = os.path.expanduser(
        os.environ.get("VAULT_PATH", "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/PHoward")
    )
    if args.source_dir:
        source_dir = Path(args.source_dir)
    else:
        # Default: per tenant config; for phil-howard, the legacy CCG opportunities dir
        # is the de facto leads source today. New platform default: ${VAULT}/Sales/Leads.
        candidates = [
            Path(vault) / "Sales" / "Leads",
            Path(vault) / "Cognitive-Capital-Group" / "Opportunities",
        ]
        source_dir = next((c for c in candidates if c.is_dir()), candidates[0])

    run = Run(SCRIPT_NAME)
    print(f"=== {SCRIPT_NAME} (tenant={args.tenant}) ===")
    print(f"source: {source_dir}")
    print()

    db_path = init_db("leads")
    records = find_records(source_dir)
    run.records_seen = len(records)
    if not records:
        print("  (no records found; created empty leads.db)")
        run.report(db_path)
        return 0

    conn = sqlite3.connect(db_path)
    for rec in records:
        if insert_lead(conn, rec, args.tenant, source_dir):
            run.records_inserted += 1
        else:
            run.records_skipped += 1
            run.errors.append(rec.slug)
    conn.commit()

    # Quick summary from views
    cur = conn.execute("SELECT stage, deal_count, raw_value FROM v_pipeline_summary ORDER BY stage")
    print("\nPipeline by stage:")
    for stage, count, value in cur:
        print(f"  {stage:15s}  {count:3d} deals  ${value or 0:>12,}")
    cur = conn.execute("SELECT COUNT(*) FROM v_overdue_actions")
    print(f"\nOverdue actions: {cur.fetchone()[0]}")
    cur = conn.execute("SELECT COUNT(*) FROM v_stuck_deals")
    print(f"Stuck deals (>30d in stage): {cur.fetchone()[0]}")
    conn.close()

    run.report(db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
