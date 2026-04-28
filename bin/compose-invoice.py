#!/usr/bin/env python3
"""Generate client-ready invoices for a contract: PDF + markdown + Gmail draft + Calendar reminder.

End-to-end flow per uninvoiced milestone:
  1. Auto-generate sequential invoice number (<ENTITY-PREFIX>-<YEAR>-<NNN>)
  2. Render branded PDF (reportlab) and markdown
  3. Save Gmail draft (with PDF attached) via google-workspace OAuth tokens
  4. Create Google Calendar reminder N days before due_date (default 7)
  5. Update contract_payment.invoice_id + invoiced_at (DB-tracked anti-duplication)

All bill-to / billing config lives on the contract markdown frontmatter
(read into the index by regenerate-contracts-index.py); no per-call CLI
flags. The first time you invoice a new contract, populate these in the
contract markdown:

  bill_to_address: |
    The University of Texas at Dallas
    Center for BrainHealth
    2200 W. Mockingbird Ln, Dallas, TX 75235
  bill_to_attention: "Attn: Accounting"
  bill_to_email: bhaccounting@utdallas.edu
  billing_account: ccg-phil       # google-workspace token (defaults to entity.billing.default_account)
  billing_payment_info: |
    Payment via electronic funds transfer per §51.012, Education Code.
    Bank details on file with BrainHealth.
  billing_notes: "Services rendered per Services Agreement 2026-2027. Exempt from Texas Sales & Use Tax."
  reminder_days_before: "7"      # null/missing disables calendar reminder

Default behavior: process all contract_payment rows for the contract that
have invoiced_at IS NULL AND paid_at IS NULL. --milestone narrows to one
specific milestone label.

Usage:
  compose-invoice.py --tenant phil-howard --contract-id sow-acme-2026q2
  compose-invoice.py --tenant phil-howard --contract-id sow-acme-2026q2 --milestone kickoff
  compose-invoice.py --tenant phil-howard --contract-id sow-acme-2026q2 --no-pdf       # markdown only
  compose-invoice.py --tenant phil-howard --contract-id sow-acme-2026q2 --no-gmail-draft
  compose-invoice.py --tenant phil-howard --contract-id sow-acme-2026q2 --dry-run
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from email import encoders
from email.message import EmailMessage
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import build_signatory_context, emit_telemetry  # noqa: E402
from _template_renderer import render  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "compose-invoice"
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))
GW_TOKENS_DIR = Path(os.path.expanduser("~/Winnie/mcp-servers/google-workspace/tokens"))


# ──────────────────────────────────────────────────────────────────────────────
# Tenant + DB
# ──────────────────────────────────────────────────────────────────────────────

def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def load_template(tenant_id: str, entity_id: str | None) -> str:
    name = "invoice-template.md"
    candidates = [
        PLATFORM_ROOT / "templates" / (entity_id or "_") / name,
        PLATFORM_ROOT / "templates" / tenant_id / name,
        PLATFORM_ROOT / "templates" / "default" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c.read_text()
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
    if not CONTRACTS_DB.is_file():
        return f"{prefix}-{year}-001"
    pattern = f"{prefix}-{year}-%"
    conn = sqlite3.connect(CONTRACTS_DB)
    rows = conn.execute(
        "SELECT invoice_id FROM contract_payment WHERE invoice_id LIKE ?",
        (pattern,),
    ).fetchall()
    conn.close()
    rx = re.compile(rf"^{re.escape(prefix)}-{year}-(\d+)$")
    seqs: list[int] = []
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


def mark_invoiced(payment_id: int, invoice_number: str, invoiced_at_iso: str) -> bool:
    if not CONTRACTS_DB.is_file():
        return False
    conn = sqlite3.connect(CONTRACTS_DB)
    try:
        conn.execute(
            "UPDATE contract_payment SET invoice_id = ?, invoiced_at = ? WHERE id = ?",
            (invoice_number, invoiced_at_iso, payment_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def entity_prefix(entity: dict) -> str:
    if entity.get("invoice_prefix"):
        return entity["invoice_prefix"]
    return (entity.get("id") or "INV").upper().replace("-", "")


# ──────────────────────────────────────────────────────────────────────────────
# Google API helpers (Gmail draft + Calendar reminder via stored OAuth tokens)
# ──────────────────────────────────────────────────────────────────────────────

def gw_service(account: str, api: str):
    """Build a Google API client (gmail|calendar) using the stored token cache."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

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
    return build(api, "v1" if api == "gmail" else "v3",
                  credentials=creds, cache_discovery=False)


def create_gmail_draft(account: str, to: str, subject: str, body: str,
                         attachment_path: Path | None) -> str | None:
    """Create a Gmail draft with optional PDF attachment. Returns draft id."""
    svc = gw_service(account, "gmail")
    if svc is None:
        return None
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment_path and attachment_path.is_file():
        with attachment_path.open("rb") as f:
            data = f.read()
        msg.add_attachment(data, maintype="application", subtype="pdf",
                            filename=attachment_path.name)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        result = svc.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}
        ).execute()
        return result.get("id")
    except Exception as e:
        print(f"  ! gmail draft failed for {account}: {e}", file=sys.stderr)
        return None


def create_calendar_reminder(account: str, when: date, title: str,
                                description: str) -> str | None:
    """Create a 30-min calendar event N days before invoice due date."""
    svc = gw_service(account, "calendar")
    if svc is None:
        return None
    start = datetime.combine(when, datetime.min.time().replace(hour=9))
    end = start + timedelta(minutes=30)
    body = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": "America/New_York"},
        "end":   {"dateTime": end.isoformat(),   "timeZone": "America/New_York"},
        "reminders": {"useDefault": False, "overrides": [
            {"method": "popup", "minutes": 60},
            {"method": "email", "minutes": 24 * 60},
        ]},
    }
    try:
        result = svc.events().insert(calendarId="primary", body=body).execute()
        return result.get("id")
    except Exception as e:
        print(f"  ! calendar reminder failed for {account}: {e}", file=sys.stderr)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# PDF rendering (ported + parameterized from Cowork recurring-invoice-setup)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class InvoiceRenderContext:
    invoice_number: str
    invoice_date: date
    due_date: date
    payment_terms: str
    contract_ref: str
    company_name: str
    company_address_lines: list[str]
    company_email: str
    bill_to_lines: list[str]
    bill_to_attention: str
    bill_to_email: str
    line_items: list[tuple[str, str, int]]   # (description, period, amount_cents)
    subtotal: int
    tax: int
    total_due: int
    payment_info_lines: list[str]
    notes_lines: list[str]
    accent_color_hex: str


def render_pdf(ctx: InvoiceRenderContext, out_path: Path) -> bool:
    """Render a one-page invoice PDF. Returns True on success."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.lib.colors import HexColor, white, black
        from reportlab.pdfgen import canvas
    except ImportError:
        print("  ! reportlab not installed — skipping PDF", file=sys.stderr)
        return False

    WIDTH, HEIGHT = letter
    accent = HexColor(ctx.accent_color_hex)
    c = canvas.Canvas(str(out_path), pagesize=letter)

    # Header
    c.setFont("Helvetica-Bold", 18)
    c.drawString(0.75 * inch, HEIGHT - 0.75 * inch, ctx.company_name)
    c.setFont("Helvetica", 9)
    y = HEIGHT - 0.95 * inch
    for line in ctx.company_address_lines + [ctx.company_email]:
        if not line:
            continue
        c.drawString(0.75 * inch, y, line)
        y -= 0.13 * inch

    c.setFont("Helvetica", 36)
    c.setFillColor(accent)
    c.drawRightString(WIDTH - 0.75 * inch, HEIGHT - 0.85 * inch, "INVOICE")
    c.setFillColor(black)

    bar_y = HEIGHT - 1.55 * inch
    c.setFillColor(accent)
    c.rect(0.75 * inch, bar_y, WIDTH - 1.5 * inch, 6, fill=1, stroke=0)

    # Bill to
    section_top = bar_y - 0.35 * inch
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(black)
    c.drawString(0.75 * inch, section_top, "BILL TO")
    y = section_top - 0.22 * inch
    c.setFont("Helvetica", 9)
    for line in ctx.bill_to_lines:
        c.drawString(0.75 * inch, y, line)
        y -= 0.16 * inch
    if ctx.bill_to_attention:
        c.drawString(0.75 * inch, y, ctx.bill_to_attention)
        y -= 0.16 * inch
    if ctx.bill_to_email:
        c.drawString(0.75 * inch, y, ctx.bill_to_email)

    # Invoice details
    detail_x = 4.25 * inch
    value_x = 5.75 * inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(detail_x, section_top, "INVOICE DETAILS")
    y = section_top - 0.22 * inch
    details = [
        ("Invoice #:", ctx.invoice_number, True),
        ("Invoice Date:", ctx.invoice_date.strftime("%B %d, %Y"), False),
        ("Due Date:", ctx.due_date.strftime("%B %d, %Y"), False),
        ("Terms:", ctx.payment_terms, False),
        ("Reference:", ctx.contract_ref, False),
    ]
    for label, val, bold_val in details:
        c.setFont("Helvetica", 9)
        c.drawString(detail_x, y, label)
        c.setFont("Helvetica-Bold" if bold_val else "Helvetica", 9)
        c.drawString(value_x, y, val)
        y -= 0.16 * inch

    # Line items table
    table_top = section_top - 1.55 * inch
    c.setFillColor(accent)
    c.rect(0.75 * inch, table_top - 0.02 * inch, WIDTH - 1.5 * inch, 0.28 * inch, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(0.85 * inch, table_top + 0.03 * inch, "DESCRIPTION")
    c.drawString(5.0 * inch, table_top + 0.03 * inch, "PERIOD")
    c.drawRightString(WIDTH - 0.85 * inch, table_top + 0.03 * inch, "AMOUNT")
    c.setFillColor(black)

    row_y = table_top - 0.35 * inch
    for desc, period, cents in ctx.line_items:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(0.85 * inch, row_y, desc[:52])
        c.setFont("Helvetica", 9)
        c.drawCentredString(5.35 * inch, row_y, period)
        c.drawRightString(WIDTH - 0.85 * inch, row_y, f"${cents/100:,.2f}")
        row_y -= 0.32 * inch

    # Separator
    sep_y = row_y - 0.08 * inch
    c.setStrokeColor(accent)
    c.setLineWidth(0.5)
    c.line(0.75 * inch, sep_y, WIDTH - 0.75 * inch, sep_y)

    # Totals
    totals_y = sep_y - 0.4 * inch
    c.setFont("Helvetica", 9)
    c.drawRightString(5.8 * inch, totals_y, "Subtotal:")
    c.drawRightString(WIDTH - 0.85 * inch, totals_y, f"${ctx.subtotal/100:,.2f}")
    totals_y -= 0.22 * inch
    c.drawRightString(5.8 * inch, totals_y, "Tax:" if ctx.tax > 0 else "Tax (Exempt):")
    c.drawRightString(WIDTH - 0.85 * inch, totals_y, f"${ctx.tax/100:,.2f}")
    totals_y -= 0.32 * inch
    c.setFillColor(accent)
    c.rect(4.6 * inch, totals_y - 0.05 * inch, WIDTH - 4.6 * inch - 0.75 * inch,
           0.28 * inch, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(5.8 * inch, totals_y, "TOTAL DUE:")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(WIDTH - 0.85 * inch, totals_y, f"${ctx.total_due/100:,.2f}")

    # Bottom bar
    bottom_bar_y = totals_y - 0.6 * inch
    c.setFillColor(accent)
    c.rect(0.75 * inch, bottom_bar_y, WIDTH - 1.5 * inch, 6, fill=1, stroke=0)

    # Payment info / notes
    info_y = bottom_bar_y - 0.4 * inch
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, info_y, "PAYMENT INFORMATION")
    c.setFont("Helvetica", 8.5)
    pay_y = info_y - 0.2 * inch
    for line in ctx.payment_info_lines or ["Wire instructions provided separately."]:
        c.drawString(0.75 * inch, pay_y, line[:90])
        pay_y -= 0.15 * inch

    c.setFont("Helvetica-Bold", 10)
    c.drawString(4.25 * inch, info_y, "NOTES")
    c.setFont("Helvetica", 8.5)
    notes_y = info_y - 0.2 * inch
    for line in ctx.notes_lines or [""]:
        c.drawString(4.25 * inch, notes_y, line[:60])
        notes_y -= 0.15 * inch

    # Thank you
    ty_y = min(pay_y, notes_y) - 0.5 * inch
    c.setFont("Helvetica-Oblique", 10)
    c.setFillColor(accent)
    c.drawCentredString(WIDTH / 2, ty_y, "Thank you for your business.")

    c.save()
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def _hourly_synthesize_payment(contract: dict, args) -> list[dict]:
    """For hourly billing: read calendar over [period-start, period-end],
    compute billable minutes via the same rules as time-billable.py, then
    INSERT a contract_payment row representing the period and return it
    (loaded back) for the standard invoice pipeline.

    Idempotency: the milestone label encodes the period, so a second call
    over the same window will detect the existing invoiced row and exit.
    """
    # Defer import so callers using only milestone mode aren't taxed.
    # time-billable.py has a hyphen so import_module won't work.
    # Use spec_from_file_location to load it as a module on the fly.
    # Register in sys.modules BEFORE exec_module so @dataclass works
    # (Python 3.14's dataclass machinery walks sys.modules).
    tb_path = Path(__file__).resolve().parent / "time-billable.py"
    spec = importlib.util.spec_from_file_location("_time_billable", tb_path)
    tb = importlib.util.module_from_spec(spec)
    sys.modules["_time_billable"] = tb
    spec.loader.exec_module(tb)

    if not contract.get("hourly_rate"):
        sys.exit(f"error: hourly billing requires hourly_rate on contract {contract['id']!r}")

    period_days = contract.get("billing_period_days") or 30
    end_d = (datetime.fromisoformat(args.period_end).date()
              if args.period_end else date.today())
    start_d = (datetime.fromisoformat(args.period_start).date()
                if args.period_start else (end_d - timedelta(days=period_days)))
    if start_d >= end_d:
        sys.exit("error: period-start must be before period-end")

    milestone_label = f"hourly-{start_d.isoformat()}-to-{end_d.isoformat()}"

    # Idempotency: if a payment row already exists for this label, refuse to
    # double-invoice. Caller can pass --period-start/-end to invoice a different window.
    conn = sqlite3.connect(CONTRACTS_DB)
    existing = conn.execute(
        "SELECT id, invoice_id FROM contract_payment "
        "WHERE contract_id = ? AND milestone = ?",
        (contract["id"], milestone_label),
    ).fetchone()
    conn.close()
    if existing:
        sys.exit(f"error: hourly payment for window {milestone_label} already recorded "
                  f"(payment_id={existing[0]}, invoice_id={existing[1]}); choose a different window")

    # Run the calendar classify
    domains = set(tb.split_csv(contract.get("billing_client_domains")))
    emails = set(tb.split_csv(contract.get("billing_client_emails")))
    pattern = contract.get("billing_work_block_pattern")
    if not domains and not emails and not pattern:
        sys.exit(f"error: hourly contract {contract['id']!r} has no match config "
                  "(billing_client_domains / _emails / _work_block_pattern all empty)")
    granularity = contract.get("billing_round_to_minutes") or 15
    account = (contract.get("billing_calendar_account")
                or contract.get("billing_account") or "ccg-phil")

    svc = tb.calendar_service(account)
    start_dt = datetime.combine(start_d, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end_d + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc)
    events = tb.fetch_events(svc, start_dt, end_dt)
    total_minutes = 0
    for e in events:
        rule, _ = tb.classify(e, domains, emails, pattern)
        if not rule:
            continue
        s_dt, e_dt, mins = tb.event_duration_minutes(e)
        if mins <= 0:
            continue
        total_minutes += tb.round_up_to(mins, granularity)
    if total_minutes <= 0:
        return []

    hours = total_minutes / 60.0
    amount = round(hours * contract["hourly_rate"])
    print(f"  hourly compute: {total_minutes} min ({hours:.2f} hr) @ ${contract['hourly_rate']:,}/hr = ${amount:,}")

    # Insert a fresh contract_payment row representing the billed window
    conn = sqlite3.connect(CONTRACTS_DB)
    cur = conn.execute("""
        INSERT INTO contract_payment (
          contract_id, milestone, amount, due_trigger, due_date
        ) VALUES (?, ?, ?, ?, ?)
    """, (contract["id"], milestone_label, amount,
          f"hourly:{hours:.2f}h@${contract['hourly_rate']}/hr",
          (end_d + timedelta(days=30)).isoformat()))
    conn.commit()
    payment_id = cur.lastrowid
    row = conn.execute("SELECT * FROM contract_payment WHERE id = ?", (payment_id,)).fetchone()
    conn.close()
    # Return as list[dict] in the same shape as load_uninvoiced_payments
    cols = [d[0] for d in sqlite3.connect(CONTRACTS_DB).execute(
        "SELECT * FROM contract_payment LIMIT 0").description]
    return [dict(zip(cols, row))]


def first_nonempty_line(s: str | None) -> str:
    if not s:
        return ""
    for line in s.splitlines():
        if line.strip():
            return line.strip()
    return ""


def split_lines(s: str | None) -> list[str]:
    if not s:
        return []
    return [ln.strip() for ln in s.splitlines() if ln.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--contract-id", required=True)
    parser.add_argument("--milestone", help="Limit to one milestone label (default: all uninvoiced)")
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--no-gmail-draft", action="store_true")
    parser.add_argument("--no-calendar-reminder", action="store_true")
    parser.add_argument("--invoice-date", help="ISO YYYY-MM-DD; default today")
    parser.add_argument("--due-days", type=int, default=30)
    parser.add_argument("--payment-terms", default="Net 30")
    parser.add_argument("--reminder-days-before", type=int,
                        help="Override contract.reminder_days_before (default: 7)")
    parser.add_argument("--signatory", help="Override default signatory")
    parser.add_argument("--billing-mode",
                        help="Override contract.billing_mode for this run "
                             "(milestone | hourly). When 'hourly', --period-start/-end "
                             "drive the calendar-based time accumulation.")
    parser.add_argument("--period-start", help="hourly mode: ISO YYYY-MM-DD")
    parser.add_argument("--period-end",   help="hourly mode: ISO YYYY-MM-DD; default today")
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

    billing_mode = args.billing_mode or contract.get("billing_mode") or "milestone"

    if billing_mode == "hourly":
        payments = _hourly_synthesize_payment(contract, args)
        if not payments:
            sys.exit("error: hourly mode found 0 billable minutes in the period; nothing to invoice")
    else:
        payments = load_uninvoiced_payments(args.contract_id, args.milestone)
        if not payments:
            sys.exit(f"error: no uninvoiced payment milestones for contract {args.contract_id!r}"
                      + (f" matching milestone={args.milestone!r}" if args.milestone else ""))

    # Required billing fields — fail fast if absent
    if not contract.get("bill_to_address"):
        sys.exit(f"error: contract {args.contract_id!r} missing bill_to_address. "
                  "Add to contract markdown frontmatter and run regenerate-contracts-index.")

    today = datetime.now().date()
    invoice_date = (datetime.fromisoformat(args.invoice_date).date()
                     if args.invoice_date else today)
    due_date = invoice_date + timedelta(days=args.due_days)

    billing = (entity.get("billing") or {})
    accent_color = billing.get("pdf_accent_color") or "#2E5F8A"
    company_email = billing.get("email") or sig_ctx.get("signatory_email") or ""
    account = (contract.get("billing_account")
                or billing.get("default_account")
                or "ccg-phil")

    reminder_days = (args.reminder_days_before
                      if args.reminder_days_before is not None
                      else int(contract.get("reminder_days_before") or 7))

    # Pre-render company / bill-to lines
    company_address_lines = split_lines(entity.get("address"))
    bill_to_lines = split_lines(contract.get("bill_to_address"))
    bill_to_attention = contract.get("bill_to_attention") or ""
    bill_to_email = contract.get("bill_to_email") or ""
    payment_info_lines = split_lines(contract.get("billing_payment_info"))
    notes_lines = split_lines(contract.get("billing_notes"))

    print(f"=== compose-invoice (v0.2) ===")
    print(f"contract:       {contract['display_name']} ({args.contract_id})")
    print(f"entity:         {entity['id']}")
    print(f"milestones:     {len(payments)} uninvoiced")
    print(f"account:        {account}")
    print(f"reminder days:  {reminder_days} before due")
    print()

    vault = Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"]))
    out_dir = vault / "Finance" / "Invoices" / entity["id"]
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    template_text = load_template(args.tenant, entity["id"])
    prefix = entity_prefix(entity)
    year = invoice_date.year
    invoiced_at_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    issued_count = 0
    pdf_count = 0
    draft_count = 0
    reminder_count = 0
    failures: list[str] = []
    # In dry-run, mark_invoiced never commits, so next_invoice_number would
    # return the same value every iteration. Track a local counter for preview.
    dry_run_counter = 0

    # Process one milestone at a time so each gets its own number
    for p in payments:
        if args.dry_run:
            base_seq_str = next_invoice_number(prefix, year).rsplit("-", 1)[1]
            base_seq = int(base_seq_str) + dry_run_counter
            invoice_number = f"{prefix}-{year}-{base_seq:03d}"
            dry_run_counter += 1
        else:
            invoice_number = next_invoice_number(prefix, year)

        # Markdown rendering
        deal = {
            "invoice_number":       invoice_number,
            "invoice_date":         invoice_date.strftime("%Y-%m-%d"),
            "due_date":             due_date.strftime("%Y-%m-%d"),
            "payment_terms":        args.payment_terms,
            "contract_id":          args.contract_id,
            "bill_to_name":         first_nonempty_line(contract.get("bill_to_address")),
            "bill_to_address":      contract.get("bill_to_address"),
            "bill_to_attention":    bill_to_attention or "—",
            "line_item_1":          p["milestone"],
            "line_item_1_amount":   f"{p['amount']:,}",
            "line_item_2":          "—",
            "line_item_2_amount":   "0",
            "line_item_3":          "—",
            "line_item_3_amount":   "0",
            "subtotal":             f"{p['amount']:,}",
            "tax_amount":           "0",
            "total_due":            f"{p['amount']:,}",
            "payment_instructions": contract.get("billing_payment_info") or "Wire instructions provided separately.",
            "notes":                contract.get("billing_notes") or "",
        }
        entity_ctx = {**entity, "tax_id": billing.get("tax_id") or "TBD"}
        context = {
            "tenant": {**sig_ctx},
            "entity":   entity_ctx,
            "deal":     deal,
            "today":    today.strftime("%Y-%m-%d"),
        }
        rendered = render(template_text, context)

        print(f"  - {invoice_number}  {p['milestone']:30s} ${p['amount']:>10,}")

        if args.dry_run:
            issued_count += 1
            continue

        # Markdown
        md_path = out_dir / f"{invoice_number}.md"
        if md_path.exists():
            shutil.copy2(md_path, md_path.with_suffix(f".prev-{int(time.time())}.md"))
        md_path.write_text(rendered.text)
        print(f"    wrote: {md_path.relative_to(vault)}")

        # PDF
        pdf_path: Path | None = None
        if not args.no_pdf:
            ctx = InvoiceRenderContext(
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                due_date=due_date,
                payment_terms=args.payment_terms,
                contract_ref=args.contract_id,
                company_name=entity.get("legal_name", "TBD"),
                company_address_lines=company_address_lines,
                company_email=company_email,
                bill_to_lines=bill_to_lines,
                bill_to_attention=bill_to_attention,
                bill_to_email=bill_to_email,
                line_items=[(p["milestone"],
                              p.get("due_date") or "—",
                              p["amount"] * 100)],
                subtotal=p["amount"] * 100,
                tax=0,
                total_due=p["amount"] * 100,
                payment_info_lines=payment_info_lines,
                notes_lines=notes_lines,
                accent_color_hex=accent_color,
            )
            pdf_candidate = out_dir / f"{invoice_number}.pdf"
            if render_pdf(ctx, pdf_candidate):
                pdf_path = pdf_candidate
                pdf_count += 1
            else:
                failures.append(f"{invoice_number}:pdf")

        # Voice sweep on markdown
        if (entity.get("brand") or {}).get("no_em_dash"):
            subprocess.run(
                [str(Path.home() / "Winnie" / "bin" / "voice-sweep.sh"), str(md_path)],
                capture_output=True, text=True, timeout=10,
            )

        # Gmail draft (with PDF attached if available)
        if not args.no_gmail_draft and bill_to_email:
            subject = f"{entity.get('display_name', entity['id'])} Invoice {invoice_number}"
            body = (
                f"Hi,\n\n"
                f"Please see attached invoice {invoice_number} for {p['milestone']}, "
                f"in the amount of ${p['amount']:,}, due {due_date.strftime('%B %d, %Y')}.\n\n"
                f"{contract.get('billing_notes') or ''}\n\n"
                f"Thank you,\n"
                f"{sig_ctx.get('signatory_name', '')}\n"
                f"{entity.get('legal_name', '')}\n"
            )
            draft_id = create_gmail_draft(account, bill_to_email, subject, body, pdf_path)
            if draft_id:
                draft_count += 1
            else:
                failures.append(f"{invoice_number}:draft")

        # Calendar reminder N days before due
        if not args.no_calendar_reminder and reminder_days >= 0:
            reminder_date = due_date - timedelta(days=reminder_days)
            title = f"Send invoice {invoice_number} to {first_nonempty_line(contract.get('bill_to_address'))}"
            description = (
                f"Invoice: {invoice_number}\n"
                f"Amount: ${p['amount']:,}\n"
                f"Due: {due_date.strftime('%B %d, %Y')}\n"
                f"PDF: {pdf_path.relative_to(vault) if pdf_path else 'not generated'}\n"
                f"Markdown: {md_path.relative_to(vault)}\n"
                f"Gmail draft: open Gmail Drafts and search '{invoice_number}'."
            )
            event_id = create_calendar_reminder(account, reminder_date, title, description)
            if event_id:
                reminder_count += 1
            else:
                failures.append(f"{invoice_number}:reminder")

        # Mark DB
        mark_invoiced(p["id"], invoice_number, invoiced_at_iso)
        issued_count += 1

    print()
    print(f"issued:    {issued_count}")
    print(f"pdfs:      {pdf_count}")
    print(f"drafts:    {draft_count}")
    print(f"reminders: {reminder_count}")
    if failures:
        print(f"failures:  {len(failures)}: {failures[:5]}")

    emit_telemetry(SCRIPT_NAME, outcome="success" if not failures else "partial_failure",
                   contract_id=args.contract_id,
                   entity=entity["id"],
                   milestones_processed=issued_count,
                   pdfs_generated=pdf_count,
                   gmail_drafts=draft_count,
                   calendar_reminders=reminder_count,
                   failures=len(failures),
                   dry_run=int(args.dry_run),
                   duration_seconds=round(time.time() - start, 2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
