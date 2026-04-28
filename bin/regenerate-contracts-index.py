#!/usr/bin/env python3
"""Regenerate contracts.db from per-contract markdown files.

Source:  ${VAULT}/Legal/Contracts/<slug>.md  (per tenant; configurable)
Target:  ~/.local/state/alpen/sqlite/contracts.db

Usage:
  regenerate-contracts-index.py --tenant phil-howard
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

SCRIPT_NAME = "regenerate-contracts-index"


def status_normalize(s: str | None) -> str:
    if not s:
        return "DRAFT"
    n = s.strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "draft": "DRAFT",
        "in_review": "IN_REVIEW",
        "review": "IN_REVIEW",
        "negotiating": "NEGOTIATING",
        "sent": "SENT_FOR_SIGNATURE",
        "sent_for_signature": "SENT_FOR_SIGNATURE",
        "partially_signed": "SIGNED_PARTIAL",
        "signed_partial": "SIGNED_PARTIAL",
        "signed": "EXECUTED",
        "executed": "EXECUTED",
        "active": "EXECUTED",
        "amended": "AMENDED",
        "expired": "EXPIRED",
        "terminated": "TERMINATED",
        "voided": "VOIDED",
        "void": "VOIDED",
    }
    return mapping.get(n, "DRAFT")


def type_normalize(t: str | None) -> str:
    if not t:
        return "OTHER"
    n = t.strip().upper().replace("-", "_").replace(" ", "_")
    if n in {"MSA", "SOW", "NDA", "LOI", "AMENDMENT", "OTHER"}:
        return n
    return "OTHER"


def insert_contract(conn: sqlite3.Connection, rec, tenant_id: str, source_dir: Path) -> bool:
    fm = rec.fm
    vault_path = str(rec.path.relative_to(source_dir.parent.parent)) if source_dir.parent.parent in rec.path.parents else str(rec.path)
    try:
        conn.execute("""
            INSERT INTO contract (
              id, tenant_id, entity_id, contract_type, parent_contract_id,
              display_name, contracting_entity_us, contracting_entity_them,
              signatory_us, signatory_them, status,
              effective_date, termination_date, total_value, governing_law,
              drafted_at, sent_at, signed_us_at, signed_them_at, executed_at,
              terminated_at, termination_reason,
              lead_id, engagement_id, vault_path, pdf_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rec.slug,
            tenant_id,
            coerce_str(fm.get("entity_id")) or "ccg",
            type_normalize(fm.get("type") or fm.get("contract_type")),
            coerce_str(fm.get("parent_contract_id") or fm.get("parent_msa")),
            coerce_str(fm.get("name")) or rec.slug,
            coerce_str(fm.get("contracting_entity_us") or fm.get("us_entity")) or "TBD",
            coerce_str(fm.get("contracting_entity_them") or fm.get("counterparty")) or "TBD",
            coerce_str(fm.get("signatory_us")) or "TBD",
            coerce_str(fm.get("signatory_them")),
            status_normalize(fm.get("status")),
            coerce_date(fm.get("effective_date") or fm.get("start_date")),
            coerce_date(fm.get("termination_date") or fm.get("end_date")),
            parse_money(fm.get("total_value") or fm.get("value")),
            coerce_str(fm.get("governing_law")),
            None, None,  # drafted_at, sent_at — populated by workflow events later
            coerce_date(fm.get("signed_us_at")),
            coerce_date(fm.get("signed_them_at")),
            coerce_date(fm.get("executed_at") or fm.get("contract_signed")),
            coerce_date(fm.get("terminated_at")),
            coerce_str(fm.get("termination_reason")),
            coerce_str(fm.get("lead_id") or fm.get("linked_opportunity")),
            coerce_str(fm.get("engagement_id")),
            vault_path,
            coerce_str(fm.get("pdf_path")),
        ))
    except sqlite3.IntegrityError as e:
        print(f"  ! integrity error inserting {rec.slug}: {e}", file=sys.stderr)
        return False
    # Optional: payment schedule rows from frontmatter
    payments = fm.get("payments") or []
    if isinstance(payments, list):
        for p in payments:
            if not isinstance(p, dict):
                continue
            try:
                conn.execute("""
                    INSERT INTO contract_payment (contract_id, milestone, amount, due_trigger, due_date, invoice_id, invoiced_at, paid_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rec.slug,
                    coerce_str(p.get("milestone")) or "unknown",
                    parse_money(p.get("amount")) or 0,
                    coerce_str(p.get("due_trigger")) or "manual",
                    coerce_date(p.get("due_date")),
                    coerce_str(p.get("invoice_id")),
                    coerce_date(p.get("invoiced_at")),
                    coerce_date(p.get("paid_at")),
                ))
            except Exception as e:
                print(f"  ! payment row skipped for {rec.slug}: {e}", file=sys.stderr)
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
            Path(vault) / "Legal" / "Contracts",
            Path(vault) / "Cognitive-Capital-Group" / "Contracts",
        ]
        source_dir = next((c for c in candidates if c.is_dir()), candidates[0])

    run = Run(SCRIPT_NAME)
    print(f"=== {SCRIPT_NAME} (tenant={args.tenant}) ===")
    print(f"source: {source_dir}")
    print()

    db_path = init_db("contracts")
    records = find_records(source_dir)
    run.records_seen = len(records)

    if not records:
        print("  (no records found; created empty contracts.db)")
        run.report(db_path)
        return 0

    conn = sqlite3.connect(db_path)
    for rec in records:
        if insert_contract(conn, rec, args.tenant, source_dir):
            run.records_inserted += 1
        else:
            run.records_skipped += 1
            run.errors.append(rec.slug)
    conn.commit()

    cur = conn.execute("SELECT COUNT(*), SUM(COALESCE(total_value, 0)) FROM v_active_contracts")
    n, total = cur.fetchone()
    print(f"\nActive contracts: {n}, total value: ${total or 0:,}")
    cur = conn.execute("SELECT COUNT(*) FROM v_renewals_upcoming")
    print(f"Renewals upcoming (90d): {cur.fetchone()[0]}")
    cur = conn.execute("SELECT COUNT(*) FROM v_payments_outstanding")
    print(f"Outstanding payments: {cur.fetchone()[0]}")
    conn.close()

    run.report(db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
