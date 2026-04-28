#!/usr/bin/env python3
"""Bulk-insert monthly contract_payment rows for a subscription contract.

Generates N monthly milestone rows so that month-end-billing.py's
"non-hourly mode" path picks up one milestone per month and runs
compose-invoice automatically on the 1st.

Each row uses:
  milestone   = "monthly-YYYY-MM"
  amount      = monthly_amount (or cap-adjusted on the final month)
  due_trigger = "calendar:YYYY-MM-DD" (the period end date)
  due_date    = period end (last day of that calendar month)

Idempotency: scans existing contract_payment rows and skips months that
already have a milestone='monthly-<month>' label. Safe to re-run.

Cap behavior: if --total-cap is set and monthly_amount * months exceeds
the cap, the FINAL month is adjusted down so the sum equals the cap
exactly. Mirrors the Cowork recurring-invoice-setup pattern Krystal uses
for BrainHealth-style fixed-total contracts.

Usage:
  setup-recurring-payments.py --tenant phil-howard \\
      --contract-id sub-acme-platform-2026 \\
      --start-month 2026-05 --months 12 --monthly-amount 1500

  setup-recurring-payments.py --tenant phil-howard \\
      --contract-id sub-utdallas-brainhealth-2026 \\
      --start-month 2026-03 --months 12 --monthly-amount 16667 \\
      --total-cap 200000

  setup-recurring-payments.py --tenant phil-howard \\
      --contract-id sub-acme-platform-2026 \\
      --start-month 2026-05 --months 12 --monthly-amount 1500 --dry-run
"""

from __future__ import annotations

import argparse
import calendar
import os
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "setup-recurring-payments"
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))


def load_contract(cid: str) -> dict | None:
    if not CONTRACTS_DB.is_file():
        return None
    conn = sqlite3.connect(CONTRACTS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM contract WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def existing_monthly_labels(contract_id: str) -> set[str]:
    if not CONTRACTS_DB.is_file():
        return set()
    conn = sqlite3.connect(CONTRACTS_DB)
    rows = conn.execute(
        "SELECT milestone FROM contract_payment "
        "WHERE contract_id = ? AND milestone LIKE 'monthly-%'",
        (contract_id,),
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


def parse_month(s: str) -> tuple[int, int]:
    y, m = s.split("-")
    return int(y), int(m)


def add_months(year: int, month: int, n: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + n
    return total // 12, (total % 12) + 1


def last_day_of(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def insert_payment(contract_id: str, milestone: str, amount: int,
                    due_date: date) -> bool:
    conn = sqlite3.connect(CONTRACTS_DB)
    try:
        conn.execute("""
            INSERT INTO contract_payment (
              contract_id, milestone, amount, due_trigger, due_date
            ) VALUES (?, ?, ?, ?, ?)
        """, (contract_id, milestone, amount,
              f"calendar:{due_date.isoformat()}", due_date.isoformat()))
        conn.commit()
        return True
    except sqlite3.IntegrityError as e:
        print(f"  ! integrity error for {milestone}: {e}", file=sys.stderr)
        return False
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--contract-id", required=True)
    parser.add_argument("--start-month", required=True,
                        help="YYYY-MM of the first billable month")
    parser.add_argument("--months", type=int, required=True, help="Number of months to generate")
    parser.add_argument("--monthly-amount", type=int, required=True,
                        help="USD per month (whole dollars)")
    parser.add_argument("--total-cap", type=int,
                        help="USD total cap; if set, final month is adjusted to match exactly")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.months < 1 or args.months > 60:
        sys.exit("error: --months must be between 1 and 60")

    start = time.time()
    contract = load_contract(args.contract_id)
    if not contract:
        sys.exit(f"error: contract {args.contract_id!r} not in contracts.db")

    mode = contract.get("billing_mode") or "milestone"
    if mode not in ("subscription", "monthly"):
        print(f"  ! warning: contract billing_mode={mode!r}; expected 'subscription' or 'monthly'. "
               "Continuing — month-end-billing.py will still pick these up if mode is one of those.",
               file=sys.stderr)

    sy, sm = parse_month(args.start_month)
    existing = existing_monthly_labels(args.contract_id)

    print(f"=== {SCRIPT_NAME} ===")
    print(f"contract:        {contract['display_name']} ({args.contract_id})")
    print(f"start month:     {args.start_month}")
    print(f"months:          {args.months}")
    print(f"monthly amount:  ${args.monthly_amount:,}")
    if args.total_cap:
        print(f"total cap:       ${args.total_cap:,}")
    print(f"existing labels: {len(existing)}")

    # Pre-compute amounts (with cap adjustment on last month if applicable)
    amounts = [args.monthly_amount] * args.months
    if args.total_cap:
        proposed_total = args.monthly_amount * args.months
        if proposed_total > args.total_cap:
            adjust = args.total_cap - args.monthly_amount * (args.months - 1)
            if adjust < 0:
                sys.exit(f"error: cap ${args.total_cap:,} too low for {args.months - 1} months "
                          f"@ ${args.monthly_amount:,} = ${args.monthly_amount * (args.months - 1):,}")
            amounts[-1] = adjust
            print(f"final month adjusted to ${adjust:,} to hit cap exactly")

    inserted = 0
    skipped = 0
    rows: list[tuple[str, int, str]] = []
    for i in range(args.months):
        yy, mm = add_months(sy, sm, i)
        label = f"monthly-{yy:04d}-{mm:02d}"
        due = last_day_of(yy, mm)
        amt = amounts[i]
        if label in existing:
            print(f"  - {label}  ${amt:,}  (already exists, skip)")
            skipped += 1
            continue
        marker = "[DRY-RUN]" if args.dry_run else "[INSERT]"
        rows.append((label, amt, due.isoformat()))
        if not args.dry_run:
            if insert_payment(args.contract_id, label, amt, due):
                inserted += 1
                print(f"  {marker} {label}  ${amt:,}  due {due.isoformat()}")
            else:
                print(f"  ! {label} insert failed", file=sys.stderr)
        else:
            print(f"  {marker} {label}  ${amt:,}  due {due.isoformat()}")

    summed = sum(a for (_, a, _) in rows) + sum(args.monthly_amount for _ in range(skipped))
    print()
    print(f"inserted: {inserted} (would-insert in dry-run: {len(rows)})")
    print(f"skipped:  {skipped}")
    print(f"summed (new + skipped at default rate): ${summed:,}")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   contract_id=args.contract_id,
                   inserted=inserted,
                   skipped=skipped,
                   total_months=args.months,
                   monthly_amount=args.monthly_amount,
                   total_cap=args.total_cap or 0,
                   dry_run=int(args.dry_run),
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
