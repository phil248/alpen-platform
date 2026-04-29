#!/usr/bin/env python3
"""Generate a per-entity revenue report for a given quarter or year-to-date.

Reads contracts.db.contract_payment for invoiced + paid amounts. Aggregates
by entity, then by contract, then lists each invoice. Output goes to
$VAULT/Finance/Reports/YYYY-Q<N>-revenue.md (or YYYY-YTD-revenue.md).

Used at quarter-end / year-end for tax prep, board reviews, or just
sanity-checking the billing pipeline. On-demand by default; can be
scheduled if needed (compose-qbr-style fire on quarter-end).

Usage:
  revenue-rollup.py --tenant phil-howard                  # YTD this year
  revenue-rollup.py --tenant phil-howard --quarter 2026-Q2
  revenue-rollup.py --tenant phil-howard --year 2026      # full year
  revenue-rollup.py --tenant phil-howard --dry-run        # stdout only
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "revenue-rollup"
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def vault_path(tenant_cfg: dict) -> Path:
    raw = tenant_cfg.get("tenant", {}).get("vault_path") or os.environ.get("VAULT_PATH")
    if not raw:
        sys.exit("error: tenant.vault_path not set and VAULT_PATH not in env")
    return Path(os.path.expanduser(raw))


QUARTER_BOUNDS = {
    1: ("01-01", "03-31"),
    2: ("04-01", "06-30"),
    3: ("07-01", "09-30"),
    4: ("10-01", "12-31"),
}


def resolve_period(args) -> tuple[str, date, date]:
    """Return (label, start_date, end_date) inclusive."""
    if args.quarter:
        m = re.match(r"^(\d{4})-Q([1-4])$", args.quarter)
        if not m:
            sys.exit("error: --quarter must look like '2026-Q2'")
        y, q = int(m.group(1)), int(m.group(2))
        s, e = QUARTER_BOUNDS[q]
        return (f"{y}-Q{q}",
                date.fromisoformat(f"{y}-{s}"),
                date.fromisoformat(f"{y}-{e}"))
    if args.year:
        y = int(args.year)
        return (f"{y}",
                date(y, 1, 1),
                date(y, 12, 31))
    # Default: YTD
    today = date.today()
    return (f"{today.year}-YTD",
            date(today.year, 1, 1),
            today)


def query_invoices(start: date, end: date) -> list[dict]:
    """Return invoiced contract_payment rows where invoiced_at falls in
    [start, end]. Joins contract for display fields."""
    if not CONTRACTS_DB.is_file():
        return []
    conn = sqlite3.connect(CONTRACTS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT cp.id, cp.contract_id, cp.milestone, cp.amount,
               cp.invoice_id, cp.invoiced_at, cp.due_date,
               cp.paid_at, cp.paid_amount,
               ct.entity_id, ct.display_name AS contract_name,
               ct.contracting_entity_them, ct.billing_mode
        FROM contract_payment cp
        JOIN contract ct ON ct.id = cp.contract_id
        WHERE cp.invoiced_at IS NOT NULL
          AND date(cp.invoiced_at) BETWEEN ? AND ?
        ORDER BY ct.entity_id, ct.id, cp.invoiced_at
    """, (start.isoformat(), end.isoformat())).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def group_by(rows: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out


def format_amount(cents_or_dollars: int) -> str:
    return f"${cents_or_dollars:,}"


def render_report(label: str, start: date, end: date, rows: list[dict]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    out = [
        f"# Revenue rollup — {label}",
        "",
        f"_Period: {start} -> {end} (inclusive). Generated {today}._",
        "_Source: contracts.db.contract_payment, contract_payment.invoiced_at within period._",
        "",
    ]

    if not rows:
        out += ["## No invoices in this period",
                "",
                "Nothing was invoiced (`invoiced_at IS NOT NULL` AND in window). "
                "If you expected revenue here, check the period bounds and that the "
                "invoices were marked invoiced (compose-invoice records this)."]
        return "\n".join(out) + "\n"

    # Top-level summary
    total_inv = sum(r["amount"] or 0 for r in rows)
    total_col = sum((r["paid_amount"] or r["amount"] or 0) for r in rows if r["paid_at"])
    out += [
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Invoices issued | {len(rows)} |",
        f"| Total invoiced | **{format_amount(total_inv)}** |",
        f"| Total collected | **{format_amount(total_col)}** |",
        f"| Outstanding | {format_amount(total_inv - total_col)} |",
        "",
    ]

    # Per-entity breakdown
    by_entity = group_by(rows, "entity_id")
    out += ["## By entity", "",
             "| Entity | Invoiced | Collected | Outstanding | Invoices | Open |",
             "|---|---|---|---|---|---|"]
    for entity_id in sorted(by_entity.keys()):
        ent_rows = by_entity[entity_id]
        ent_inv = sum(r["amount"] or 0 for r in ent_rows)
        ent_col = sum((r["paid_amount"] or r["amount"] or 0) for r in ent_rows if r["paid_at"])
        open_count = sum(1 for r in ent_rows if not r["paid_at"])
        out.append(f"| {entity_id} | {format_amount(ent_inv)} | {format_amount(ent_col)} "
                    f"| {format_amount(ent_inv - ent_col)} | {len(ent_rows)} | {open_count} |")
    out.append("")

    # Per-contract breakdown
    out += ["## By contract", "",
             "| Entity | Contract | Client | Mode | Invoiced | Collected | Open |",
             "|---|---|---|---|---|---|---|"]
    by_contract: dict[tuple, list[dict]] = {}
    for r in rows:
        key = (r["entity_id"], r["contract_id"])
        by_contract.setdefault(key, []).append(r)
    for (eid, cid), c_rows in sorted(by_contract.items()):
        c_inv = sum(r["amount"] or 0 for r in c_rows)
        c_col = sum((r["paid_amount"] or r["amount"] or 0) for r in c_rows if r["paid_at"])
        c_open = sum(1 for r in c_rows if not r["paid_at"])
        sample = c_rows[0]
        out.append(f"| {eid} | {sample['contract_name']} (`{cid}`) | "
                    f"{sample['contracting_entity_them']} | {sample['billing_mode']} | "
                    f"{format_amount(c_inv)} | {format_amount(c_col)} | {c_open} |")
    out.append("")

    # Invoice-level detail
    out += ["## Invoice detail (chronological)", "",
             "| Invoice | Date | Entity | Client | Milestone | Amount | Paid |",
             "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x["invoiced_at"] or "")):
        date_str = (r["invoiced_at"] or "")[:10]
        paid_str = "—"
        if r["paid_at"]:
            paid_amount = r["paid_amount"] or r["amount"]
            paid_str = f"{format_amount(paid_amount)} on {(r['paid_at'] or '')[:10]}"
        out.append(f"| {r['invoice_id']} | {date_str} | {r['entity_id']} | "
                    f"{r['contracting_entity_them']} | {r['milestone']} | "
                    f"{format_amount(r['amount'] or 0)} | {paid_str} |")
    out.append("")

    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--quarter", help="YYYY-QN (default: YTD this year)")
    grp.add_argument("--year", type=int, help="full calendar year")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print to stdout; don't write to vault")
    parser.add_argument("--out-path", help="Override output path")
    args = parser.parse_args()

    if not CONTRACTS_DB.is_file():
        sys.exit(f"error: contracts.db not found at {CONTRACTS_DB}")

    start_t = time.time()
    tenant_cfg = load_tenant_cfg(args.tenant)
    vault = vault_path(tenant_cfg)
    label, start, end = resolve_period(args)

    rows = query_invoices(start, end)
    print(f"=== {SCRIPT_NAME} ===")
    print(f"period:    {label}  ({start} -> {end})")
    print(f"invoices:  {len(rows)}")
    if rows:
        total_inv = sum(r["amount"] or 0 for r in rows)
        total_col = sum((r["paid_amount"] or r["amount"] or 0) for r in rows if r["paid_at"])
        print(f"invoiced:  ${total_inv:,}")
        print(f"collected: ${total_col:,}")

    report = render_report(label, start, end, rows)
    if args.dry_run:
        print()
        print(report)
    else:
        out_dir = vault / "Finance" / "Reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = Path(args.out_path) if args.out_path else (out_dir / f"{label}-revenue.md")
        out_path.write_text(report)
        print(f"wrote: {out_path}")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   period=label,
                   invoices=len(rows),
                   invoiced_total=sum(r["amount"] or 0 for r in rows),
                   collected_total=sum((r["paid_amount"] or r["amount"] or 0)
                                         for r in rows if r["paid_at"]),
                   duration_seconds=round(time.time() - start_t, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
