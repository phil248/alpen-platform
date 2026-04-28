#!/usr/bin/env python3
"""Generate a milestone (or recurring monthly) invoice from contract_payment rows.

Reads:
  contracts.db          — contract + contract_payment rows
  templates/<entity-or-default>/invoice-template.md
  tenant config         — bill-from + bill-to defaults

Writes:
  ${VAULT}/Finance/Invoices/<entity>/<invoice-number>.md
  contracts.db.contract_payment.invoice_id + invoiced_at  (for each line)

Invoice numbering: <ENTITY-PREFIX>-<YEAR>-<NNN>
  - prefix: tenant config entities[].invoice_prefix, falls back to entity.id.upper()
  - NNN: 1 + max sequence already issued under that prefix this year

Usage:
  # Invoice all unpaid + uninvoiced milestones for a contract
  compose-invoice.py --tenant phil-howard --contract-id sow-acme-2026q2 \\
    --bill-to-name "Acme Pharma" --bill-to-address "123 Main, NYC NY 10001" \\
    --bill-to-attention "AP Department"

  # Invoice only one specific milestone
  compose-invoice.py --tenant phil-howard --contract-id sow-acme-2026q2 \\
    --milestone kickoff --bill-to-name "Acme Pharma"

  # Dry run (preview without writing)
  compose-invoice.py --tenant phil-howard --contract-id sow-acme-2026q2 --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import build_signatory_context, emit_telemetry  # noqa: E402
from _template_renderer import render  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "compose-invoice"
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def load_template(tenant_id: str, entity_id: str | None) -> tuple[Path, str]:
    name = "invoice-template.md"
    candidates = [
        PLATFORM_ROOT / "templates" / (entity_id or "_") / name,
        PLATFORM_ROOT / "templates" / tenant_id / name,
        PLATFORM_ROOT / "templates" / "default" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c, c.read_text()
    sys.exit("error: invoice-template not found")


def load_contract(cid: str) -> dict | None:
    if not CONTRACTS_DB.is_file():
        return None
    conn = sqlite3.connect(CONTRACTS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM contract WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def load_uninvoiced_payments(cid: str, milestone_filter: str | None) -> list[dict]:
    if not CONTRACTS_DB.is_file():
        return []
    conn = sqlite3.connect(CONTRACTS_DB)
    conn.row_factory = sqlite3.Row
    sql = ("SELECT * FROM contract_payment WHERE contract_id = ? "
           "AND invoiced_at IS NULL AND paid_at IS NULL")
    params: list = [cid]
    if milestone_filter:
        sql += " AND milestone = ?"
        params.append(milestone_filter)
    sql += " ORDER BY id ASC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def next_invoice_number(prefix: str, year: int) -> str:
    """Compute next invoice number under <prefix>-<year>-NNN by scanning
    contract_payment.invoice_id values."""
    if not CONTRACTS_DB.is_file():
        return f"{prefix}-{year}-001"
    pattern = f"{prefix}-{year}-%"
    conn = sqlite3.connect(CONTRACTS_DB)
    rows = conn.execute(
        "SELECT invoice_id FROM contract_payment WHERE invoice_id LIKE ?",
        (pattern,),
    ).fetchall()
    conn.close()
    seqs: list[int] = []
    rx = re.compile(rf"^{re.escape(prefix)}-{year}-(\d+)$")
    for (val,) in rows:
        if not val:
            continue
        m = rx.match(val)
        if m:
            try:
                seqs.append(int(m.group(1)))
            except ValueError:
                pass
    nxt = (max(seqs) + 1) if seqs else 1
    return f"{prefix}-{year}-{nxt:03d}"


def mark_invoiced(payment_ids: list[int], invoice_number: str, invoiced_at_iso: str) -> bool:
    if not CONTRACTS_DB.is_file() or not payment_ids:
        return False
    conn = sqlite3.connect(CONTRACTS_DB)
    try:
        for pid in payment_ids:
            conn.execute(
                "UPDATE contract_payment SET invoice_id = ?, invoiced_at = ? WHERE id = ?",
                (invoice_number, invoiced_at_iso, pid),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def entity_prefix(entity: dict) -> str:
    """Return the invoice prefix for this entity (config override or upper(id))."""
    if entity.get("invoice_prefix"):
        return entity["invoice_prefix"]
    return (entity.get("id") or "INV").upper().replace("-", "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--contract-id", required=True)
    parser.add_argument("--milestone", help="One milestone label to invoice (default: all uninvoiced)")
    parser.add_argument("--bill-to-name", help="Override contract.contracting_entity_them")
    parser.add_argument("--bill-to-address", default="TBD")
    parser.add_argument("--bill-to-attention", default="Accounts Payable")
    parser.add_argument("--invoice-date", help="ISO YYYY-MM-DD; default today")
    parser.add_argument("--due-days", type=int, default=30, help="default Net 30")
    parser.add_argument("--payment-terms", default="Net 30")
    parser.add_argument("--payment-instructions",
                        default="Wire instructions provided separately. ACH preferred.")
    parser.add_argument("--tax-amount", type=int, default=0,
                        help="USD; default 0 (services typically exempt)")
    parser.add_argument("--notes", default="Thank you for your business.")
    parser.add_argument("--signatory", help="principal id of OUR signer (overrides default)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = time.time()
    tenant_cfg = load_tenant_cfg(args.tenant)
    contract = load_contract(args.contract_id)
    if not contract:
        sys.exit(f"error: contract {args.contract_id!r} not in contracts.db")

    entity = next((e for e in tenant_cfg["entities"] if e.get("id") == contract["entity_id"]),
                   tenant_cfg["entities"][0])
    sig_ctx = build_signatory_context(tenant_cfg, entity["id"], args.signatory)

    payments = load_uninvoiced_payments(args.contract_id, args.milestone)
    if not payments:
        sys.exit(f"error: no uninvoiced payment milestones for contract {args.contract_id!r}"
                  + (f" matching milestone={args.milestone!r}" if args.milestone else ""))

    today = datetime.now()
    invoice_date = args.invoice_date or today.strftime("%Y-%m-%d")
    due_date = (today + timedelta(days=args.due_days)).strftime("%Y-%m-%d")
    prefix = entity_prefix(entity)
    invoice_number = next_invoice_number(prefix, today.year)

    # Sum line items
    subtotal = sum(p["amount"] for p in payments)
    total = subtotal + (args.tax_amount or 0)

    # Pad up to 3 line slots in the template; extras concatenate as a single line for now
    li = list(payments)
    deal = {
        "invoice_number":       invoice_number,
        "invoice_date":         invoice_date,
        "due_date":             due_date,
        "payment_terms":        args.payment_terms,
        "contract_id":          args.contract_id,
        "bill_to_name":         args.bill_to_name or contract["contracting_entity_them"],
        "bill_to_address":      args.bill_to_address,
        "bill_to_attention":    args.bill_to_attention,
        "line_item_1":          (li[0]["milestone"] if len(li) >= 1 else ""),
        "line_item_1_amount":   (f"{li[0]['amount']:,}" if len(li) >= 1 else "0"),
        "line_item_2":          (li[1]["milestone"] if len(li) >= 2 else "—"),
        "line_item_2_amount":   (f"{li[1]['amount']:,}" if len(li) >= 2 else "0"),
        "line_item_3":          (li[2]["milestone"] if len(li) >= 3 else "—"),
        "line_item_3_amount":   (f"{li[2]['amount']:,}" if len(li) >= 3 else "0"),
        "subtotal":             f"{subtotal:,}",
        "tax_amount":           f"{args.tax_amount:,}",
        "total_due":            f"{total:,}",
        "payment_instructions": args.payment_instructions,
        "notes":                args.notes,
    }

    # Pull bill-from from entity config
    entity_ctx = {
        **entity,
        "tax_id": entity.get("tax_id") or "TBD",
    }

    context = {
        "tenant": {**sig_ctx},
        "entity":   entity_ctx,
        "deal":     deal,
        "today":    today.strftime("%Y-%m-%d"),
    }
    rendered = render(template_text := load_template(args.tenant, entity["id"])[1], context)

    print(f"=== compose-invoice ===")
    print(f"contract:        {contract['display_name']} ({args.contract_id})")
    print(f"entity:          {entity['id']}")
    print(f"invoice number:  {invoice_number}")
    print(f"line items:      {len(payments)}")
    for p in payments:
        print(f"  - {p['milestone']:30s} ${p['amount']:>12,}")
    print(f"subtotal:        ${subtotal:,}")
    print(f"total due:       ${total:,}")
    print(f"resolved:        {len(rendered.resolved)}, unresolved: {len(rendered.unresolved)}")
    if rendered.unresolved:
        print(f"  unresolved: {rendered.unresolved}")

    if args.dry_run:
        print()
        print("--- rendered (first 60 lines) ---")
        for line in rendered.text.splitlines()[:60]:
            print(line)
        emit_telemetry(SCRIPT_NAME, outcome="success", dry_run=True,
                       contract_id=args.contract_id,
                       invoice_number=invoice_number,
                       line_count=len(payments), subtotal=subtotal)
        return 0

    vault = Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"]))
    out_dir = vault / "Finance" / "Invoices" / entity["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{invoice_number}.md"
    if out_path.exists():
        backup = out_path.with_suffix(f".prev-{int(time.time())}.md")
        shutil.copy2(out_path, backup)
    out_path.write_text(rendered.text)
    print(f"wrote: {out_path}")

    invoiced_at_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    marked = mark_invoiced([p["id"] for p in payments], invoice_number, invoiced_at_iso)
    if marked:
        print(f"contracts.db: marked {len(payments)} payment row(s) invoiced as {invoice_number}")

    sweep = "skipped"
    if (entity.get("brand") or {}).get("no_em_dash"):
        result = subprocess.run(
            [str(Path.home() / "Winnie" / "bin" / "voice-sweep.sh"), str(out_path)],
            capture_output=True, text=True, timeout=10,
        )
        sweep = "pass" if result.returncode == 0 else "fail"
        print(f"voice sweep: {sweep}")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   contract_id=args.contract_id,
                   entity=entity["id"],
                   invoice_number=invoice_number,
                   line_count=len(payments),
                   subtotal=subtotal, total=total,
                   variables_resolved=len(rendered.resolved),
                   variables_unresolved=len(rendered.unresolved),
                   marked=int(marked),
                   voice_sweep=sweep,
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
