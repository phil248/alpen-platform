#!/usr/bin/env python3
"""Auto-issue invoices on the 1st of each month for hourly + subscription contracts.

Designed to be run by launchd on the 1st at 06:30 (before standup at 07:42).
Iterates over contracts.db, finds executed contracts in scope, computes the
previous calendar month bounds, and invokes compose-invoice.py per contract.

Scope:
  - billing_mode = 'hourly': invoice the previous calendar month, calendar-derived
  - billing_mode = 'subscription' or 'milestone' with calendar:YYYY-MM-DD trigger
    payments coming due in the previous month: invoice them now (delegated to
    compose-invoice's existing milestone path)

Idempotency:
  compose-invoice.py refuses duplicate hourly windows (milestone label encodes
  start+end dates). Re-running this orchestrator on the 2nd of the month
  no-ops cleanly for already-invoiced periods.

Telemetry: emits one summary record per run with per-contract outcomes.

Usage:
  month-end-billing.py --tenant phil-howard
  month-end-billing.py --tenant phil-howard --month 2026-04   # force a specific month
  month-end-billing.py --tenant phil-howard --dry-run
"""

from __future__ import annotations

import argparse
import calendar
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "month-end-billing"
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))
COMPOSE_INVOICE = Path(__file__).resolve().parent / "compose-invoice.py"
VENV_PY = PLATFORM_ROOT / ".venv" / "bin" / "python"


def previous_month_bounds(today: date | None = None) -> tuple[date, date]:
    """Return (first_day, last_day) of the calendar month BEFORE today."""
    today = today or date.today()
    if today.month == 1:
        y, m = today.year - 1, 12
    else:
        y, m = today.year, today.month - 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last)


def explicit_month_bounds(month_str: str) -> tuple[date, date]:
    """Parse 'YYYY-MM' to (first_day, last_day)."""
    y, m = month_str.split("-")
    y, m = int(y), int(m)
    last = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last)


def load_billable_contracts() -> list[dict]:
    if not CONTRACTS_DB.is_file():
        return []
    conn = sqlite3.connect(CONTRACTS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM contract
        WHERE status = 'EXECUTED'
          AND billing_mode IN ('hourly', 'subscription', 'monthly')
        ORDER BY entity_id, id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def has_milestones_due(contract_id: str, period_start: date, period_end: date) -> bool:
    """True if there's at least one uninvoiced milestone with calendar:YYYY-MM-DD
    trigger inside the previous month, or any uninvoiced row at all for
    monthly/subscription billing_mode (caller decides). Used as a hint."""
    if not CONTRACTS_DB.is_file():
        return False
    conn = sqlite3.connect(CONTRACTS_DB)
    rows = conn.execute("""
        SELECT id, due_date FROM contract_payment
        WHERE contract_id = ?
          AND invoiced_at IS NULL AND paid_at IS NULL
          AND due_date IS NOT NULL
          AND due_date >= ? AND due_date <= ?
    """, (contract_id, period_start.isoformat(), period_end.isoformat())).fetchall()
    conn.close()
    return len(rows) > 0


def run_compose_invoice(tenant: str, contract: dict, period_start: date,
                          period_end: date, dry_run: bool) -> tuple[bool, str]:
    """Invoke compose-invoice.py per contract. Returns (ok, summary_line)."""
    cmd = [
        str(VENV_PY), str(COMPOSE_INVOICE),
        "--tenant", tenant,
        "--contract-id", contract["id"],
    ]
    if (contract.get("billing_mode") or "milestone") == "hourly":
        cmd += ["--billing-mode", "hourly",
                "--period-start", period_start.isoformat(),
                "--period-end", period_end.isoformat()]
    if dry_run:
        cmd += ["--dry-run"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return True, result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "ok"
        # compose-invoice exits 1 for partial failures or "no uninvoiced milestones"
        last_lines = (result.stdout or result.stderr or "").strip().splitlines()
        return False, last_lines[-1] if last_lines else f"exit {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--month", help="YYYY-MM to force a specific period; default = previous month")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = time.time()
    if args.month:
        period_start, period_end = explicit_month_bounds(args.month)
    else:
        period_start, period_end = previous_month_bounds()

    print(f"=== {SCRIPT_NAME} (tenant={args.tenant}) ===")
    print(f"period: {period_start} -> {period_end}")
    if args.dry_run:
        print("(dry-run)")

    contracts = load_billable_contracts()
    print(f"executed billable contracts: {len(contracts)}")

    successes: list[str] = []
    failures: list[str] = []
    skipped: list[str] = []

    for c in contracts:
        mode = c.get("billing_mode") or "milestone"
        cid = c["id"]
        # For non-hourly modes, only invoke when there's a milestone actually due
        if mode != "hourly":
            if not has_milestones_due(cid, period_start, period_end):
                skipped.append(f"{cid} ({mode}, no milestones due)")
                continue
        ok, summary = run_compose_invoice(args.tenant, c, period_start, period_end, args.dry_run)
        marker = "OK" if ok else "FAIL"
        print(f"  [{marker}] {cid:30s} {summary}")
        (successes if ok else failures).append(cid)

    print()
    print(f"successes: {len(successes)}")
    print(f"failures:  {len(failures)}")
    print(f"skipped:   {len(skipped)}")
    if failures:
        for f in failures:
            print(f"  ! {f}")
    if skipped:
        for s in skipped:
            print(f"  - {s}")

    emit_telemetry(SCRIPT_NAME,
                   outcome="success" if not failures else "partial_failure",
                   tenant=args.tenant,
                   period_start=period_start.isoformat(),
                   period_end=period_end.isoformat(),
                   contracts_total=len(contracts),
                   successes=len(successes),
                   failures=len(failures),
                   skipped=len(skipped),
                   dry_run=int(args.dry_run),
                   duration_seconds=round(time.time() - start, 2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
