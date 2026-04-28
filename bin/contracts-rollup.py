#!/usr/bin/env python3
"""Generate a markdown rollup of contracts.db.

Writes ${VAULT}/Legal/Contracts.md.
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
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))
SCRIPT_NAME = "contracts-rollup"


def fmt_money(amount: int | None) -> str:
    if amount is None:
        return "—"
    return f"${amount:,}"


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
    out.append("  - legal")
    out.append("  - contracts-rollup")
    out.append(f"generated: {today_iso}")
    out.append(f"tenant: {tenant_cfg['tenant']['id']}")
    out.append("---")
    out.append("")
    out.append("# Contracts (Alpen Platform)")
    out.append("")
    out.append("> **Auto-generated** from `contracts.db`. Edit per-contract markdown source files; rerun `bin/regenerate-contracts-index.py` to refresh.")
    out.append("")

    # Active contracts
    active = list(conn.execute("""
        SELECT id, display_name, contracting_entity_them, contract_type,
               total_value, effective_date, termination_date, days_to_expiry
        FROM v_active_contracts
    """))
    out.append(f"## Active contracts ({len(active)})")
    out.append("")
    if active:
        out.append("| Contract | Counterparty | Type | Value | Effective | Termination | Days to expiry |")
        out.append("|----------|-------------|------|-------|-----------|-------------|----------------|")
        for r in active:
            dte = "—" if r[7] is None else f"{int(r[7])}d"
            out.append(f"| [[Legal/Contracts/{r[0]}\\|{r[1]}]] | {r[2]} | {r[3]} | {fmt_money(r[4])} | {fmt_date(r[5])} | {fmt_date(r[6])} | {dte} |")
    else:
        out.append("_None._")
    out.append("")

    # Renewals upcoming (90d)
    renewals = list(conn.execute("""
        SELECT id, display_name, contracting_entity_them, total_value, termination_date, days_to_expiry
        FROM v_renewals_upcoming
    """))
    out.append(f"## Renewals upcoming (next 90 days, {len(renewals)})")
    out.append("")
    if renewals:
        out.append("| Contract | Counterparty | Value | Termination | Days |")
        out.append("|----------|-------------|-------|-------------|------|")
        for r in renewals:
            out.append(f"| [[Legal/Contracts/{r[0]}\\|{r[1]}]] | {r[2]} | {fmt_money(r[3])} | {fmt_date(r[4])} | {int(r[5])} |")
    else:
        out.append("_None in the next 90 days._")
    out.append("")

    # Outstanding payments
    payments = list(conn.execute("""
        SELECT id, contract_name, milestone, amount, due_date, payment_status
        FROM v_payments_outstanding
    """))
    out.append(f"## Outstanding payments ({len(payments)})")
    out.append("")
    if payments:
        out.append("| Contract | Milestone | Amount | Due | Status |")
        out.append("|----------|-----------|--------|-----|--------|")
        for r in payments:
            out.append(f"| {r[1]} | {r[2]} | {fmt_money(r[3])} | {fmt_date(r[4])} | {r[5]} |")
    else:
        out.append("_None._")
    out.append("")

    # Flagged clauses
    flagged = list(conn.execute("""
        SELECT contract_name, clause_type, flag_reason
        FROM v_flagged_clauses
    """))
    out.append(f"## Flagged clauses (in-flight contracts, {len(flagged)})")
    out.append("")
    if flagged:
        out.append("| Contract | Clause type | Flag reason |")
        out.append("|----------|-------------|-------------|")
        for r in flagged:
            out.append(f"| {r[0]} | {r[1]} | {r[2]} |")
    else:
        out.append("_None._")
    out.append("")

    # All contracts grouped by status
    out.append("## By status")
    out.append("")
    for status in ["DRAFT", "IN_REVIEW", "NEGOTIATING", "SENT_FOR_SIGNATURE",
                   "SIGNED_PARTIAL", "EXECUTED", "AMENDED", "EXPIRED", "TERMINATED", "VOIDED"]:
        rows = list(conn.execute("""
            SELECT id, display_name, contracting_entity_them, total_value
            FROM contract WHERE status = ?
            ORDER BY total_value DESC NULLS LAST
        """, (status,)))
        if not rows:
            continue
        out.append(f"### {status.replace('_', ' ').title()} ({len(rows)})")
        out.append("")
        for r in rows:
            value_str = f" — {fmt_money(r[3])}" if r[3] else ""
            cparty_str = f" ({r[2]})" if r[2] else ""
            out.append(f"- [[Legal/Contracts/{r[0]}|{r[1]}]]{cparty_str}{value_str}")
        out.append("")

    out.append("---")
    out.append(f"_Generated {today_iso} by alpen-platform/bin/contracts-rollup.py_")
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    if not CONTRACTS_DB.is_file():
        sys.exit("error: contracts.db not found; run regenerate-contracts-index.py first")

    cfg_path = PLATFORM_ROOT / "tenants" / args.tenant / "config.yaml"
    with cfg_path.open() as f:
        tenant_cfg = yaml.safe_load(f)

    output = (Path(args.output) if args.output else
              Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"])) / "Legal" / "Contracts.md")
    output.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    conn = sqlite3.connect(CONTRACTS_DB)
    text = render_rollup(conn, tenant_cfg)
    conn.close()
    output.write_text(text)
    print(f"=== contracts-rollup ===")
    print(f"  wrote: {output} ({len(text)} chars)")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   chars_written=len(text),
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
