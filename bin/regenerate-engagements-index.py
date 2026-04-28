#!/usr/bin/env python3
"""Regenerate engagements.db from per-engagement markdown files.

Source:  ${VAULT}/Delivery/Engagements/<slug>.md  (per tenant; configurable)
Target:  ~/.local/state/alpen/sqlite/engagements.db

Usage:
  regenerate-engagements-index.py --tenant phil-howard
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import (  # noqa: E402
    Run, coerce_date, coerce_int, coerce_str, find_records, init_db, parse_money,
)

SCRIPT_NAME = "regenerate-engagements-index"


def status_normalize(s: str | None) -> str:
    if not s:
        return "NEW"
    n = s.strip().upper().replace("-", "_").replace(" ", "_")
    if n in {"NEW", "KICKOFF", "ACTIVE", "AT_RISK", "PAUSED", "CLOSED", "CANCELLED"}:
        return n
    mapping = {
        "IN_PROGRESS": "ACTIVE",
        "ON_HOLD": "PAUSED",
        "DONE": "CLOSED",
        "COMPLETED": "CLOSED",
    }
    return mapping.get(n, "NEW")


def health_color_normalize(c: str | None) -> str | None:
    if not c:
        return None
    c2 = c.strip().lower()
    if c2 in {"green", "yellow", "red"}:
        return c2
    return None


def insert_engagement(conn: sqlite3.Connection, rec, tenant_id: str, source_dir: Path) -> bool:
    fm = rec.fm
    contract_id = coerce_str(fm.get("contract_id"))
    if not contract_id:
        print(f"  ! {rec.slug} missing contract_id (required); skipping", file=sys.stderr)
        return False
    vault_path = str(rec.path.relative_to(source_dir.parent.parent)) if source_dir.parent.parent in rec.path.parents else str(rec.path)
    try:
        conn.execute("""
            INSERT INTO engagement (
              id, tenant_id, entity_id, display_name, client_name, tier, status,
              health_score, health_color,
              kickoff_date, planned_end_date, actual_end_date,
              principal_owner, client_poc_name, client_poc_email, client_sponsor_name,
              contract_id, msa_contract_id, total_value, hours_budget, vault_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rec.slug,
            tenant_id,
            coerce_str(fm.get("entity_id")) or "ccg",
            coerce_str(fm.get("name")) or rec.slug,
            coerce_str(fm.get("client_name") or fm.get("client")) or "TBD",
            coerce_int(fm.get("tier")) or 2,
            status_normalize(fm.get("status")),
            coerce_int(fm.get("health_score")),
            health_color_normalize(fm.get("health_color")),
            coerce_date(fm.get("kickoff_date")),
            coerce_date(fm.get("planned_end_date") or fm.get("end_date")),
            coerce_date(fm.get("actual_end_date")),
            coerce_str(fm.get("principal_owner") or fm.get("owner")) or "phil",
            coerce_str(fm.get("client_poc_name")),
            coerce_str(fm.get("client_poc_email")),
            coerce_str(fm.get("client_sponsor_name")),
            contract_id,
            coerce_str(fm.get("msa_contract_id") or fm.get("msa")),
            parse_money(fm.get("total_value") or fm.get("value")),
            float(fm.get("hours_budget")) if fm.get("hours_budget") else None,
            vault_path,
        ))
    except sqlite3.IntegrityError as e:
        print(f"  ! integrity error inserting {rec.slug}: {e}", file=sys.stderr)
        return False
    # Optional deliverables
    deliverables = fm.get("deliverables") or []
    if isinstance(deliverables, list):
        for i, d in enumerate(deliverables, start=1):
            if not isinstance(d, dict):
                continue
            try:
                conn.execute("""
                    INSERT INTO engagement_deliverable (
                      engagement_id, sequence, name, description, acceptance_criteria,
                      due_date, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    rec.slug, i,
                    coerce_str(d.get("name")) or f"Deliverable {i}",
                    coerce_str(d.get("description")),
                    coerce_str(d.get("acceptance_criteria")),
                    coerce_date(d.get("due_date")),
                    (coerce_str(d.get("status")) or "PLANNED").upper(),
                ))
            except Exception as e:
                print(f"  ! deliverable skipped for {rec.slug}: {e}", file=sys.stderr)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--source-dir")
    args = parser.parse_args()

    vault = os.path.expanduser(
        os.environ.get("VAULT_PATH", "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/PHoward")
    )
    if args.source_dir:
        source_dir = Path(args.source_dir)
    else:
        candidates = [
            Path(vault) / "Delivery" / "Engagements",
            Path(vault) / "Cognitive-Capital-Group" / "Engagements",
        ]
        source_dir = next((c for c in candidates if c.is_dir()), candidates[0])

    run = Run(SCRIPT_NAME)
    print(f"=== {SCRIPT_NAME} (tenant={args.tenant}) ===")
    print(f"source: {source_dir}")
    print()

    db_path = init_db("engagements", tenant_id=args.tenant)
    records = find_records(source_dir)
    run.records_seen = len(records)

    if not records:
        print("  (no records found; created empty engagements.db)")
        run.report(db_path)
        return 0

    conn = sqlite3.connect(db_path)
    for rec in records:
        if insert_engagement(conn, rec, args.tenant, source_dir):
            run.records_inserted += 1
        else:
            run.records_skipped += 1
            run.errors.append(rec.slug)
    conn.commit()

    cur = conn.execute("SELECT COUNT(*), SUM(COALESCE(total_value, 0)) FROM v_active_engagements")
    n, total = cur.fetchone()
    print(f"\nActive engagements: {n}, total value: ${total or 0:,}")
    cur = conn.execute("SELECT COUNT(*) FROM v_at_risk_engagements")
    print(f"At-risk engagements: {cur.fetchone()[0]}")
    cur = conn.execute("SELECT COUNT(*) FROM v_deliverables_upcoming")
    print(f"Deliverables due in 14d: {cur.fetchone()[0]}")
    cur = conn.execute("SELECT COUNT(*) FROM v_status_report_overdue")
    print(f"Status reports overdue: {cur.fetchone()[0]}")
    conn.close()

    run.report(db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
