#!/usr/bin/env python3
"""Enrich active leads with Gmail touchpoint state.

For each active lead (stage NOT IN WON/LOST/DISQUALIFIED) with a contact_email,
queries Gmail for the most recent inbound (prospect -> us) and outbound (us ->
prospect) message. Surfaces three actionable buckets:

  1. Recent prospect activity (inbound within last 7 days) — Phil should reply
  2. Awaiting reply (outbound > 7 days ago, no inbound after) — follow up
  3. Cold (no email either direction in 30+ days) — re-engage or close

Output goes to ${VAULT}/_Inbox/YYYY-MM-DD-lead-touchpoints.md as a daily
review document. Phil applies updates to lead frontmatter manually (the
script does NOT auto-mutate leads.db — markdown stays the source of truth).

Authenticates against the ccg-phil and alpen-phil Google Workspace tokens
that the existing google-workspace MCP server already manages. Reuses
those tokens directly via google-api-python-client; no MCP roundtrip.

Usage:
  lead-enrich-from-email.py --tenant phil-howard
  lead-enrich-from-email.py --tenant phil-howard --since-days 60
  lead-enrich-from-email.py --tenant phil-howard --account ccg-phil  # one account
  lead-enrich-from-email.py --tenant phil-howard --dry-run

Telemetry: emits leads_checked, recent_replies, awaiting_reply, cold,
no_email, accounts_used, duration_seconds.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "lead-enrich-from-email"

GWORKSPACE_DIR = Path(os.path.expanduser("~/Winnie/mcp-servers/google-workspace"))
TOKENS_DIR = GWORKSPACE_DIR / "tokens"
LEADS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/leads.db"))


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def vault_path(tenant_cfg: dict) -> Path:
    raw = tenant_cfg.get("tenant", {}).get("vault_path") or os.environ.get("VAULT_PATH")
    if not raw:
        sys.exit("error: tenant.vault_path not set and VAULT_PATH not in env")
    return Path(os.path.expanduser(raw))


def gmail_service(account: str):
    """Build a Gmail API client using the existing google-workspace token cache."""
    # Imports here so the script doesn't fail if google-api-python-client missing
    # for non-email use cases.
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
    token_path = TOKENS_DIR / f"{account}.json"
    if not token_path.is_file():
        return None
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            return None
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def search_touchpoints(svc, contact_email: str, since_days: int) -> dict:
    """Return {last_inbound: dt|None, last_outbound: dt|None, count: int}.

    Uses Gmail search to find both directions in one query, then classifies
    each hit by whether contact_email appears in From or To/Cc.
    """
    contact_email = contact_email.strip().lower()
    q = f'(from:{contact_email} OR to:{contact_email}) newer_than:{since_days}d'
    try:
        result = svc.users().messages().list(userId="me", q=q, maxResults=25).execute()
    except Exception as e:
        return {"error": str(e), "last_inbound": None, "last_outbound": None, "count": 0}

    msgs = result.get("messages", []) or []
    last_inbound = None
    last_outbound = None
    for m in msgs:
        try:
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "To", "Cc", "Date"],
            ).execute()
        except Exception:
            continue
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        date_str = headers.get("Date", "")
        if not date_str:
            continue
        try:
            dt = parsedate_to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        from_email = parseaddr(headers.get("From", ""))[1].lower()
        to_field = headers.get("To", "") + " " + headers.get("Cc", "")
        if contact_email in from_email:
            if last_inbound is None or dt > last_inbound:
                last_inbound = dt
        elif contact_email in to_field.lower():
            if last_outbound is None or dt > last_outbound:
                last_outbound = dt

    return {
        "last_inbound": last_inbound,
        "last_outbound": last_outbound,
        "count": len(msgs),
    }


def days_ago(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).days


def classify(tp: dict, since_days: int) -> str:
    """Return one of: recent_inbound | awaiting_reply | cold | no_email | error."""
    if "error" in tp:
        return "error"
    li = tp.get("last_inbound")
    lo = tp.get("last_outbound")
    if li is None and lo is None:
        return "no_email"
    in_days = days_ago(li)
    out_days = days_ago(lo)
    # Inbound within last 7d trumps everything: prospect just engaged
    if in_days is not None and in_days <= 7:
        return "recent_inbound"
    # Outbound within last 30d, no inbound newer -> awaiting reply
    if out_days is not None and out_days <= 30 and (in_days is None or in_days > out_days):
        if out_days >= 7:
            return "awaiting_reply"
        else:
            # Just sent (< 7d ago); not yet stale
            return "in_flight"
    return "cold"


def render_section(label: str, items: list[dict]) -> list[str]:
    if not items:
        return []
    out = [f"### {label}"]
    out.append("")
    out.append("| Lead | Owner | Stage | Contact | Last in | Last out | Value |")
    out.append("|---|---|---|---|---|---|---|")
    for it in items:
        last_in = "—" if it["in_days"] is None else f"{it['in_days']}d ago"
        last_out = "—" if it["out_days"] is None else f"{it['out_days']}d ago"
        value = f"${it['value']:,}" if it.get("value") else "—"
        out.append(
            f"| {it['display_name']} | {it['owner'] or '—'} | {it['stage']} | "
            f"{it['contact_email']} | {last_in} | {last_out} | {value} |"
        )
    out.append("")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--since-days", type=int, default=90)
    parser.add_argument("--account", action="append",
                        help="Account label(s) to query (default: ccg-phil + alpen-phil). "
                             "Repeat for multiple.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print to stdout; don't write the inbox file.")
    parser.add_argument("--out-path", help="Override output path")
    args = parser.parse_args()

    if not LEADS_DB.is_file():
        sys.exit(f"error: leads.db not found at {LEADS_DB}; run regenerate-leads-index.py first")

    tenant_cfg = load_tenant_cfg(args.tenant)
    vault = vault_path(tenant_cfg)

    # Default to ccg-phil + alpen-phil (Phil's two business accounts where leads land)
    accounts = args.account or ["ccg-phil", "alpen-phil"]

    # Build one Gmail service per account
    svcs: dict[str, object] = {}
    for acct in accounts:
        svc = gmail_service(acct)
        if svc is None:
            print(f"  ! {acct}: token missing or invalid; skipping", file=sys.stderr)
            continue
        svcs[acct] = svc
    if not svcs:
        sys.exit("error: no usable Google Workspace tokens; run the MCP server's --auth-only flow")

    start = time.time()
    print(f"=== {SCRIPT_NAME} (tenant={args.tenant}) ===")
    print(f"accounts: {', '.join(svcs.keys())}")
    print(f"window:   last {args.since_days} days")

    # Pull active leads with a contact email
    conn = sqlite3.connect(LEADS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, display_name, owner, stage, value_estimate, contact_email, entity_id
        FROM lead
        WHERE stage NOT IN ('WON', 'LOST', 'DISQUALIFIED')
          AND contact_email IS NOT NULL AND contact_email != ''
        ORDER BY value_estimate DESC NULLS LAST
    """).fetchall()
    conn.close()
    print(f"leads with email: {len(rows)}")

    buckets = {"recent_inbound": [], "awaiting_reply": [], "in_flight": [],
               "cold": [], "no_email": [], "error": []}

    for r in rows:
        contact = r["contact_email"]
        # Try ccg-phil first for ccg leads, alpen-phil first for alpen leads
        order = ["ccg-phil", "alpen-phil"] if r["entity_id"] == "ccg" else ["alpen-phil", "ccg-phil"]
        order = [a for a in order if a in svcs]
        # Merge results across accounts (lead might appear in either)
        merged = {"last_inbound": None, "last_outbound": None, "count": 0}
        last_err = None
        for acct in order:
            tp = search_touchpoints(svcs[acct], contact, args.since_days)
            if "error" in tp:
                last_err = tp["error"]
                continue
            merged["count"] += tp["count"]
            for key in ("last_inbound", "last_outbound"):
                v = tp[key]
                if v and (merged[key] is None or v > merged[key]):
                    merged[key] = v
        if merged["count"] == 0 and last_err:
            merged["error"] = last_err

        cls = classify(merged, args.since_days)
        item = {
            "id": r["id"],
            "display_name": r["display_name"],
            "owner": r["owner"],
            "stage": r["stage"],
            "value": r["value_estimate"],
            "contact_email": contact,
            "in_days": days_ago(merged.get("last_inbound")),
            "out_days": days_ago(merged.get("last_outbound")),
            "count": merged["count"],
        }
        buckets[cls].append(item)

    # Print summary to stdout
    for k in ("recent_inbound", "awaiting_reply", "in_flight", "cold", "no_email", "error"):
        print(f"  {k:18s} {len(buckets[k])}")

    # Render markdown
    today = datetime.now().strftime("%Y-%m-%d")
    md_lines = [
        f"# Lead touchpoint review — {today}",
        "",
        f"_Source: leads.db × Gmail. Window: {args.since_days} days. "
        f"Accounts: {', '.join(svcs.keys())}._",
        "",
        "## Action buckets",
        "",
    ]
    md_lines += render_section(
        "Recent prospect activity (inbound ≤ 7d) — REPLY",
        sorted(buckets["recent_inbound"], key=lambda x: x["in_days"] or 999),
    )
    md_lines += render_section(
        "Awaiting reply (outbound 7-30d, no inbound after) — follow up",
        sorted(buckets["awaiting_reply"], key=lambda x: x["out_days"] or 0, reverse=True),
    )
    md_lines += render_section(
        "Cold (no email in last 30d) — re-engage or close out",
        sorted(buckets["cold"], key=lambda x: -(x["value"] or 0)),
    )
    md_lines += render_section(
        "No email at all in last %d days — verify contact still active" % args.since_days,
        sorted(buckets["no_email"], key=lambda x: -(x["value"] or 0)),
    )
    if buckets["in_flight"]:
        md_lines += render_section(
            "In flight (we just sent < 7d ago)",
            sorted(buckets["in_flight"], key=lambda x: x["out_days"] or 0),
        )
    if buckets["error"]:
        md_lines += render_section("Errors fetching touchpoints", buckets["error"])

    out_text = "\n".join(md_lines)
    if args.dry_run:
        print()
        print(out_text)
    else:
        out_path = Path(args.out_path) if args.out_path else (vault / "_Inbox" / f"{today}-lead-touchpoints.md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_text)
        print(f"\nwrote: {out_path}")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   leads_checked=len(rows),
                   recent_replies=len(buckets["recent_inbound"]),
                   awaiting_reply=len(buckets["awaiting_reply"]),
                   in_flight=len(buckets["in_flight"]),
                   cold=len(buckets["cold"]),
                   no_email=len(buckets["no_email"]),
                   errors=len(buckets["error"]),
                   accounts_used=len(svcs),
                   since_days=args.since_days,
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
