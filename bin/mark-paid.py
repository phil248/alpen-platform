#!/usr/bin/env python3
"""Mark an invoiced contract_payment as paid. Closes the billing loop.

Looks up the row by invoice_id, stamps paid_at + paid_amount, drops the
row out of v_payments_outstanding (and the standup section that reads it).

Optionally creates a Google Tasks entry on personal-phil for the next
post-payment action: thank-you / revenue tracker update.

Partial payments (paid_amount < amount) are supported but do NOT clear
paid_at — the row stays in v_payments_outstanding. To fully close, run
once with --amount equal to the remaining balance, or omit --amount to
default to the full invoiced amount.

Usage:
  mark-paid.py --tenant phil-howard --invoice ALPENTECH-2026-001
  mark-paid.py --tenant phil-howard --invoice CCG-2026-005 --paid-on 2026-05-15
  mark-paid.py --tenant phil-howard --invoice CCG-2026-005 --amount 12500 --notes "wire received minus $500 retainer"
  mark-paid.py --tenant phil-howard --invoice CCG-2026-005 --no-task   # skip the follow-up task
  mark-paid.py --tenant phil-howard --invoice CCG-2026-005 --dry-run
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "mark-paid"
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))
GW_TOKENS_DIR = Path(os.path.expanduser("~/Winnie/mcp-servers/google-workspace/tokens"))


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def find_payment(invoice_number: str) -> dict | None:
    if not CONTRACTS_DB.is_file():
        return None
    conn = sqlite3.connect(CONTRACTS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("""
        SELECT cp.*, c.display_name AS contract_name,
               c.contracting_entity_them, c.entity_id, c.id AS contract_id_fk
        FROM contract_payment cp
        JOIN contract c ON c.id = cp.contract_id
        WHERE cp.invoice_id = ?
    """, (invoice_number,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_payment(payment_id: int, paid_at_iso: str, paid_amount: int,
                    notes: str | None) -> bool:
    if not CONTRACTS_DB.is_file():
        return False
    conn = sqlite3.connect(CONTRACTS_DB)
    try:
        conn.execute("""
            UPDATE contract_payment
            SET paid_at = ?, paid_amount = ?,
                notes = COALESCE(?, notes)
            WHERE id = ?
        """, (paid_at_iso, paid_amount, notes, payment_id))
        conn.commit()
        return True
    finally:
        conn.close()


def update_partial_payment(payment_id: int, paid_amount: int,
                             notes: str | None) -> bool:
    """For partial payments: stamp paid_amount + notes but DO NOT set paid_at.
    The row stays in v_payments_outstanding for the remaining balance."""
    if not CONTRACTS_DB.is_file():
        return False
    conn = sqlite3.connect(CONTRACTS_DB)
    try:
        conn.execute("""
            UPDATE contract_payment
            SET paid_amount = ?, notes = COALESCE(?, notes)
            WHERE id = ?
        """, (paid_amount, notes, payment_id))
        conn.commit()
        return True
    finally:
        conn.close()


def create_followup_task(account: str, payment: dict, paid_amount: int,
                           paid_on: date) -> str | None:
    """Create a Google Task for the post-payment action sequence."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        return None

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.settings.basic",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/tasks",
    ]
    token_path = GW_TOKENS_DIR / f"{account}.json"
    if not token_path.is_file():
        return None
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            return None
    svc = build("tasks", "v1", credentials=creds, cache_discovery=False)

    title = (f"Post-payment: log ${paid_amount:,} from "
              f"{payment['contracting_entity_them']} "
              f"(invoice {payment['invoice_id']})")
    notes = (
        f"Payment received {paid_on.isoformat()}.\n"
        f"Contract: {payment['contract_name']} ({payment['contract_id']})\n"
        f"Invoice: {payment['invoice_id']}\n"
        f"Milestone: {payment['milestone']}\n"
        f"Amount: ${paid_amount:,}\n\n"
        "Suggested actions:\n"
        "1. Update revenue tracker / accounting.\n"
        "2. Send a brief thank-you reply to the AP contact.\n"
        "3. Verify wire posted to the right operating account."
    )
    try:
        body = {
            "title": title,
            "notes": notes,
            "due": datetime.combine(paid_on, datetime.min.time()).strftime("%Y-%m-%dT00:00:00Z"),
        }
        result = svc.tasks().insert(tasklist="@default", body=body).execute()
        return result.get("id")
    except Exception as e:
        print(f"  ! task creation failed: {e}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--invoice", required=True, help="invoice_id to look up")
    parser.add_argument("--amount", type=int,
                        help="USD; default = full invoiced amount. Less than full = partial.")
    parser.add_argument("--paid-on", help="ISO YYYY-MM-DD; default today")
    parser.add_argument("--notes", help="optional notes on the payment row")
    parser.add_argument("--no-task", action="store_true",
                        help="Skip creating the post-payment Google Task")
    parser.add_argument("--task-account", default="personal-phil")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = time.time()
    payment = find_payment(args.invoice)
    if not payment:
        sys.exit(f"error: invoice {args.invoice!r} not found in contract_payment "
                  "(invoice_id column). Did you pass the full label like CCG-2026-001?")

    if payment.get("paid_at"):
        sys.exit(f"error: invoice {args.invoice!r} already marked paid at "
                  f"{payment['paid_at']} (${payment.get('paid_amount') or 0:,}). "
                  "If this is a correction, edit contracts.db directly.")

    invoiced_amount = int(payment["amount"])
    paid_amount = args.amount if args.amount is not None else invoiced_amount
    paid_on = (datetime.fromisoformat(args.paid_on).date()
                if args.paid_on else date.today())
    is_partial = paid_amount < invoiced_amount

    print(f"=== {SCRIPT_NAME} ===")
    print(f"invoice:       {args.invoice}")
    print(f"contract:      {payment['contract_name']} ({payment['contract_id']})")
    print(f"counterparty:  {payment['contracting_entity_them']}")
    print(f"milestone:     {payment['milestone']}")
    print(f"invoiced:      ${invoiced_amount:,}")
    print(f"paying now:    ${paid_amount:,}")
    print(f"paid on:       {paid_on}")
    if is_partial:
        outstanding = invoiced_amount - paid_amount
        print(f"partial — ${outstanding:,} remaining; row stays in payments_outstanding")

    if args.dry_run:
        print("\n--- dry-run; no DB or Task changes ---")
        emit_telemetry(SCRIPT_NAME, outcome="success", dry_run=True,
                       invoice=args.invoice, paid_amount=paid_amount,
                       partial=int(is_partial))
        return 0

    if is_partial:
        ok = update_partial_payment(payment["id"], paid_amount, args.notes)
    else:
        paid_at_iso = paid_on.strftime("%Y-%m-%d %H:%M:%S")
        ok = update_payment(payment["id"], paid_at_iso, paid_amount, args.notes)
    if not ok:
        sys.exit("error: DB update failed")
    print("contracts.db updated")

    task_id: str | None = None
    if not args.no_task and not is_partial:
        task_id = create_followup_task(args.task_account, payment, paid_amount, paid_on)
        if task_id:
            print(f"google task created on {args.task_account}/@default")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   invoice=args.invoice,
                   contract_id=payment["contract_id"],
                   paid_amount=paid_amount,
                   invoiced_amount=invoiced_amount,
                   partial=int(is_partial),
                   task_created=int(task_id is not None),
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
