#!/usr/bin/env python3
"""Compute billable hours for an hourly contract from Google Calendar.

For an hourly-billed contract (billing_mode='hourly'), reads the configured
calendar over a date window and identifies billable events using:

  Rule 1: client meeting
    Phil's response = 'accepted' AND any attendee's email-domain is in
    contract.billing_client_domains. Tentative / declined / needs-action
    events are NOT billable, even if a client attends.

  Rule 2: solo work block
    Event title contains contract.billing_work_block_pattern (case-insensitive).
    Use this for blocked focus time labeled with the client name.

Either rule alone makes an event billable. Each event's duration is rounded
UP to contract.billing_round_to_minutes (default 15) to match standard
hourly-billing conventions.

Output:
  ${VAULT}/Finance/TimeLogs/<entity>/YYYY-MM-DD-<contract>.md
  Detail report: per-event table + totals + amount-if-invoiced-now.

Phil reviews this BEFORE issuing an hourly invoice. The companion script
`compose-invoice.py --billing-mode hourly` issues based on the same logic.

Usage:
  time-billable.py --tenant phil-howard --contract-id sow-innosync-2026
  time-billable.py --tenant phil-howard --contract-id sow-innosync-2026 \\
      --period-start 2026-04-01 --period-end 2026-04-30
  time-billable.py --tenant phil-howard --contract-id sow-innosync-2026 --dry-run
"""

from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "time-billable"
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))
GW_TOKENS_DIR = Path(os.path.expanduser("~/Winnie/mcp-servers/google-workspace/tokens"))


# ──────────────────────────────────────────────────────────────────────────────
# Tenant + DB helpers
# ──────────────────────────────────────────────────────────────────────────────

def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def vault_path(tenant_cfg: dict) -> Path:
    raw = tenant_cfg.get("tenant", {}).get("vault_path") or os.environ.get("VAULT_PATH")
    if not raw:
        sys.exit("error: tenant.vault_path not set and VAULT_PATH not in env")
    return Path(os.path.expanduser(raw))


def load_contract(cid: str) -> dict | None:
    if not CONTRACTS_DB.is_file():
        return None
    conn = sqlite3.connect(CONTRACTS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM contract WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def split_csv(s: str | None) -> list[str]:
    if not s:
        return []
    return [x.strip().lower() for x in s.split(",") if x.strip()]


# ──────────────────────────────────────────────────────────────────────────────
# Google Calendar
# ──────────────────────────────────────────────────────────────────────────────

def calendar_service(account: str):
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
        sys.exit(f"error: google-workspace token not found for account {account!r} at {token_path}")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            sys.exit(f"error: token for {account!r} is expired/invalid; re-auth via the MCP server")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def fetch_events(svc, start: datetime, end: datetime) -> list[dict]:
    """Pull all instances (singleEvents=True) in [start, end)."""
    out: list[dict] = []
    page_token = None
    while True:
        kwargs = {
            "calendarId": "primary",
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 250,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        result = svc.events().list(**kwargs).execute()
        out.extend(result.get("items", []) or [])
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Match logic
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class BillableEvent:
    summary: str
    start: datetime
    end: datetime
    raw_minutes: int
    rounded_minutes: int
    rule: str               # 'client_meeting' | 'work_block'
    matched_attendees: list[str]


def event_duration_minutes(event: dict) -> tuple[datetime | None, datetime | None, int]:
    """Return (start_dt, end_dt, raw_minutes). 0 if all-day or malformed."""
    s = event.get("start") or {}
    e = event.get("end") or {}
    s_str = s.get("dateTime")
    e_str = e.get("dateTime")
    if not s_str or not e_str:
        return None, None, 0
    try:
        s_dt = datetime.fromisoformat(s_str.replace("Z", "+00:00"))
        e_dt = datetime.fromisoformat(e_str.replace("Z", "+00:00"))
    except ValueError:
        return None, None, 0
    return s_dt, e_dt, max(0, int((e_dt - s_dt).total_seconds() // 60))


def round_up_to(minutes: int, granularity: int) -> int:
    if granularity <= 1 or minutes <= 0:
        return minutes
    return int(math.ceil(minutes / granularity)) * granularity


def self_response(event: dict) -> str | None:
    """Return Phil's responseStatus on the event, or None if he isn't an attendee."""
    for a in event.get("attendees", []) or []:
        if a.get("self"):
            return a.get("responseStatus")
    return None


def matched_attendee_domains(event: dict, client_domains: set[str], client_emails: set[str]) -> list[str]:
    """Return list of attendee emails that match either the client domain or email allowlist."""
    matched: list[str] = []
    for a in event.get("attendees", []) or []:
        if a.get("self") or a.get("resource"):
            continue
        email = (a.get("email") or "").lower()
        if not email:
            continue
        if email in client_emails:
            matched.append(email)
            continue
        domain = email.split("@", 1)[-1] if "@" in email else ""
        if domain and domain in client_domains:
            matched.append(email)
    return matched


def classify(event: dict, client_domains: set[str], client_emails: set[str],
             work_pattern: str | None) -> tuple[str | None, list[str]]:
    """Return (rule, matched_attendees). rule is None when not billable."""
    title = (event.get("summary") or "").lower()
    if work_pattern and work_pattern.lower() in title:
        return "work_block", []
    matched = matched_attendee_domains(event, client_domains, client_emails)
    if matched and self_response(event) == "accepted":
        return "client_meeting", matched
    return None, []


# ──────────────────────────────────────────────────────────────────────────────
# Report rendering
# ──────────────────────────────────────────────────────────────────────────────

def render_report(contract: dict, period_start: date, period_end: date,
                  billables: list[BillableEvent], skipped_count: int) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    rate = contract.get("hourly_rate") or 0
    total_minutes = sum(b.rounded_minutes for b in billables)
    total_hours = total_minutes / 60.0
    amount = round(total_hours * rate)
    out = [
        f"# Billable time review — {contract['display_name']}",
        "",
        f"_Contract: `{contract['id']}`. Probed {today}._",
        f"_Period: {period_start} -> {period_end} (inclusive). Hourly rate: ${rate:,}/hr._",
        "",
        "## Summary",
        "",
        f"| Field | Value |",
        f"|---|---|",
        f"| Billable events | {len(billables)} |",
        f"| Total billable minutes | {total_minutes} |",
        f"| Total billable hours | **{total_hours:.2f}** |",
        f"| Amount at ${rate:,}/hr | **${amount:,}** |",
        f"| Non-billable events skipped | {skipped_count} |",
        "",
        "## Detail (chronological)",
        "",
        "| Date | Event | Duration | Rounded | Rule | Match |",
        "|---|---|---|---|---|---|",
    ]
    for b in sorted(billables, key=lambda x: x.start):
        date_str = b.start.strftime("%Y-%m-%d %H:%M")
        attendees = ", ".join(b.matched_attendees) if b.matched_attendees else "—"
        out.append(f"| {date_str} | {b.summary[:60]} | {b.raw_minutes}m | {b.rounded_minutes}m | "
                    f"{b.rule} | {attendees} |")
    out.append("")
    out.append("## How this report was built")
    out.append("")
    out.append("- Calendar account: " + (contract.get("billing_calendar_account") or contract.get("billing_account") or "—"))
    domains = split_csv(contract.get("billing_client_domains"))
    emails = split_csv(contract.get("billing_client_emails"))
    pattern = contract.get("billing_work_block_pattern") or "—"
    out.append(f"- Client domains (require accepted response): {domains or '—'}")
    out.append(f"- Client emails (additional explicit list): {emails or '—'}")
    out.append(f"- Solo work-block title pattern: `{pattern}`")
    out.append(f"- Round-up granularity: {contract.get('billing_round_to_minutes', 15)} minutes")
    out.append("")
    out.append("Run `compose-invoice.py --tenant <id> --contract-id "
                f"{contract['id']} --billing-mode hourly --period-start {period_start} "
                f"--period-end {period_end}` to issue the invoice based on this review.")
    out.append("")
    return "\n".join(out)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--contract-id", required=True)
    parser.add_argument("--period-start", help="ISO YYYY-MM-DD; default = period-end - billing_period_days")
    parser.add_argument("--period-end", help="ISO YYYY-MM-DD; default = today")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout; don't write file")
    args = parser.parse_args()

    start_t = time.time()
    tenant_cfg = load_tenant_cfg(args.tenant)
    vault = vault_path(tenant_cfg)
    contract = load_contract(args.contract_id)
    if not contract:
        sys.exit(f"error: contract {args.contract_id!r} not in contracts.db")

    if (contract.get("billing_mode") or "milestone") != "hourly":
        sys.exit(f"error: contract {args.contract_id!r} has billing_mode={contract.get('billing_mode')!r}; "
                  "this script only handles 'hourly'")

    if not contract.get("hourly_rate"):
        sys.exit(f"error: contract {args.contract_id!r} missing hourly_rate")

    domains = set(split_csv(contract.get("billing_client_domains")))
    emails = set(split_csv(contract.get("billing_client_emails")))
    pattern = contract.get("billing_work_block_pattern")
    if not domains and not emails and not pattern:
        sys.exit(f"error: contract {args.contract_id!r} has no match config "
                  "(billing_client_domains / _emails / _work_block_pattern all empty)")

    period_days = contract.get("billing_period_days") or 30
    end_d = (datetime.fromisoformat(args.period_end).date()
              if args.period_end else date.today())
    start_d = (datetime.fromisoformat(args.period_start).date()
                if args.period_start else (end_d - timedelta(days=period_days)))
    if start_d >= end_d:
        sys.exit("error: period-start must be before period-end")

    granularity = contract.get("billing_round_to_minutes") or 15
    account = (contract.get("billing_calendar_account")
                or contract.get("billing_account")
                or "ccg-phil")

    print(f"=== {SCRIPT_NAME} ===")
    print(f"contract:   {contract['display_name']} ({args.contract_id})")
    print(f"account:    {account}")
    print(f"period:     {start_d} -> {end_d}")
    print(f"domains:    {sorted(domains) or '—'}")
    print(f"emails:     {sorted(emails) or '—'}")
    print(f"pattern:    {pattern or '—'}")
    print(f"round to:   {granularity} min, rate ${contract['hourly_rate']:,}/hr")

    svc = calendar_service(account)
    # Convert local-date period to UTC datetime range with 1-day padding to catch edge cases
    start_dt = datetime.combine(start_d, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end_d + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc)
    events = fetch_events(svc, start_dt, end_dt)
    print(f"events seen: {len(events)}")

    billables: list[BillableEvent] = []
    skipped = 0
    for e in events:
        rule, matched = classify(e, domains, emails, pattern)
        if not rule:
            skipped += 1
            continue
        s_dt, e_dt, mins = event_duration_minutes(e)
        if mins <= 0:
            skipped += 1
            continue
        rounded = round_up_to(mins, granularity)
        billables.append(BillableEvent(
            summary=e.get("summary") or "(no title)",
            start=s_dt, end=e_dt,
            raw_minutes=mins, rounded_minutes=rounded,
            rule=rule, matched_attendees=matched,
        ))

    total_minutes = sum(b.rounded_minutes for b in billables)
    print(f"billable:    {len(billables)} events, {total_minutes} min ({total_minutes/60:.2f} hr)")
    print(f"amount:      ${round((total_minutes/60.0) * contract['hourly_rate']):,}")

    report = render_report(contract, start_d, end_d, billables, skipped)
    if args.dry_run:
        print()
        print(report)
    else:
        out_dir = vault / "Finance" / "TimeLogs" / contract["entity_id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{end_d.isoformat()}-{contract['id']}.md"
        out_path.write_text(report)
        print(f"wrote: {out_path}")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   contract_id=args.contract_id,
                   entity=contract["entity_id"],
                   period_start=str(start_d),
                   period_end=str(end_d),
                   events_seen=len(events),
                   billable_events=len(billables),
                   billable_minutes=total_minutes,
                   skipped_events=skipped,
                   amount_usd=round((total_minutes/60.0) * (contract.get("hourly_rate") or 0)),
                   duration_seconds=round(time.time() - start_t, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
