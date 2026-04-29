#!/usr/bin/env python3
"""Bootstrap missing contact_email fields by mining Gmail history.

For each active lead with no contact_email but at least one named contact,
search Gmail across ccg-phil + alpen-phil for messages where that contact
appears in From/To/Cc. Rank candidate email addresses by frequency and
recency. Propose a primary contact_email per lead.

Output: $VAULT/_Inbox/YYYY-MM-DD-lead-email-proposals.md

Phil reviews each proposal, accepts the right one by editing the lead's
frontmatter, then runs regenerate-leads-index.py to surface the change
in leads.db. Once contact_email is set, the daily lead-enrich-from-email
job picks the lead up automatically.

This is a one-shot bootstrap; no scheduled cron. Re-run as needed when
new leads are added.

Privacy: Gmail metadata only — From/To/Cc/Date/Snippet headers. Body
content is never read. Output filters out CCG-internal addresses
(*@cognitivecapitalgroup.com, *@alpentech.ai, *@cognitivecapitalgroup.io).

Usage:
  lead-email-discovery.py --tenant phil-howard
  lead-email-discovery.py --tenant phil-howard --since-days 365
  lead-email-discovery.py --tenant phil-howard --lead-id calm-health  # one lead
  lead-email-discovery.py --tenant phil-howard --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "lead-email-discovery"
LEADS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/leads.db"))
GW_TOKENS_DIR = Path(os.path.expanduser("~/Winnie/mcp-servers/google-workspace/tokens"))

# Internal domains that should NEVER be proposed as a client contact email
INTERNAL_DOMAINS = {
    "cognitivecapitalgroup.com",
    "alpentech.ai",
    "howardfamily.io",
    "gmail.com",  # Filter consumer emails to keep noise down — Phil can override manually if a lead really uses Gmail
}


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
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def load_leads_needing_email(lead_id: str | None) -> list[dict]:
    if not LEADS_DB.is_file():
        return []
    conn = sqlite3.connect(LEADS_DB)
    conn.row_factory = sqlite3.Row
    if lead_id:
        rows = conn.execute("""
            SELECT id, display_name, company_name, primary_contact, owner, stage
            FROM lead WHERE id = ?
        """, (lead_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, display_name, company_name, primary_contact, owner, stage
            FROM lead
            WHERE stage NOT IN ('WON', 'LOST', 'DISQUALIFIED')
              AND (contact_email IS NULL OR contact_email = '')
              AND primary_contact IS NOT NULL AND primary_contact != ''
            ORDER BY id
        """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_for_contact(svc, contact_name: str, since_days: int, max_results: int = 25) -> list[dict]:
    """Search Gmail for the named contact across From/To/Cc. Returns metadata
    list (id, from, to, cc, date, snippet)."""
    # Quote the contact name to keep multi-word names together
    q = f'"{contact_name}" newer_than:{since_days}d'
    try:
        result = svc.users().messages().list(userId="me", q=q, maxResults=max_results).execute()
    except Exception as e:
        return []
    out: list[dict] = []
    for m in result.get("messages", []) or []:
        try:
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "To", "Cc", "Date"],
            ).execute()
        except Exception:
            continue
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", []) or []}
        out.append({
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "cc": headers.get("Cc", ""),
            "date": headers.get("Date", ""),
        })
    return out


def emails_from_headers(messages: list[dict], contact_name: str) -> list[tuple[str, datetime | None]]:
    """Extract candidate (email, date) pairs from message headers, filtered to
    addresses that plausibly belong to the named contact."""
    name_lower = contact_name.lower()
    name_tokens = [t for t in re.split(r"\s+", name_lower) if t]
    out: list[tuple[str, datetime | None]] = []
    for m in messages:
        try:
            dt = parsedate_to_datetime(m.get("date", ""))
        except Exception:
            dt = None
        for header_field in ("from", "to", "cc"):
            val = m.get(header_field, "")
            if not val:
                continue
            # Headers may have multiple addresses comma-separated
            for piece in val.split(","):
                display, addr = parseaddr(piece.strip())
                addr = (addr or "").lower().strip()
                if not addr or "@" not in addr:
                    continue
                domain = addr.split("@", 1)[1]
                if domain in INTERNAL_DOMAINS:
                    continue
                # Match: address local-part contains a token of the contact name,
                # OR display name contains a token of the contact name.
                local = addr.split("@", 1)[0]
                ds = (display or "").lower()
                if any(tok in local for tok in name_tokens) or any(tok in ds for tok in name_tokens):
                    out.append((addr, dt))
    return out


def rank_candidates(pairs: list[tuple[str, datetime | None]]) -> list[dict]:
    """Aggregate by email -> (count, most_recent_date). Sort by count desc,
    then date desc."""
    agg: dict[str, dict] = defaultdict(lambda: {"count": 0, "latest": None})
    for addr, dt in pairs:
        agg[addr]["count"] += 1
        if dt and (agg[addr]["latest"] is None or dt > agg[addr]["latest"]):
            agg[addr]["latest"] = dt
    out = [{"email": addr, "count": v["count"], "latest": v["latest"]}
           for addr, v in agg.items()]
    out.sort(key=lambda r: (-r["count"],
                              -(r["latest"].timestamp() if r["latest"] else 0)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--lead-id", help="Single lead instead of all needy leads")
    parser.add_argument("--since-days", type=int, default=365)
    parser.add_argument("--account", action="append",
                        help="Account label(s); default ccg-phil + alpen-phil")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print proposals instead of writing the inbox file")
    args = parser.parse_args()

    if not LEADS_DB.is_file():
        sys.exit(f"error: leads.db not found at {LEADS_DB}; run regenerate-leads-index.py first")

    tenant_cfg = load_tenant_cfg(args.tenant)
    vault = vault_path(tenant_cfg)
    accounts = args.account or ["ccg-phil", "alpen-phil"]
    svcs: dict[str, object] = {}
    for a in accounts:
        s = gmail_service(a)
        if s is None:
            print(f"  ! token missing/invalid for {a}; skipping", file=sys.stderr)
            continue
        svcs[a] = s
    if not svcs:
        sys.exit("error: no usable Google Workspace tokens")

    leads = load_leads_needing_email(args.lead_id)
    print(f"=== {SCRIPT_NAME} (tenant={args.tenant}) ===")
    print(f"accounts:        {', '.join(svcs.keys())}")
    print(f"window:          last {args.since_days} days")
    print(f"leads to mine:   {len(leads)}")

    start = time.time()
    proposals: list[dict] = []
    no_match: list[dict] = []
    api_errors = 0

    for lead in leads:
        contact = lead.get("primary_contact") or ""
        if not contact:
            continue
        all_pairs: list[tuple[str, datetime | None]] = []
        for acct, svc in svcs.items():
            try:
                msgs = search_for_contact(svc, contact, args.since_days)
                all_pairs.extend(emails_from_headers(msgs, contact))
            except Exception:
                api_errors += 1
        ranked = rank_candidates(all_pairs)
        if not ranked:
            no_match.append(lead)
            continue
        proposals.append({"lead": lead, "candidates": ranked[:3]})  # top 3

    # Render report
    today = datetime.now().strftime("%Y-%m-%d")
    md = [f"# Lead contact-email proposals — {today}", ""]
    md.append(f"_Source: {', '.join(svcs.keys())} Gmail metadata, last {args.since_days} days. "
                "Internal domains filtered out (cognitivecapitalgroup.com, alpentech.ai)._")
    md.append("")
    md.append("**To accept**: edit each lead markdown's frontmatter, add "
                "`contact_email: <chosen address>`, then run "
                "`regenerate-leads-index.py --tenant phil-howard`.")
    md.append("")
    md.append(f"## Found candidates for {len(proposals)} lead(s)")
    md.append("")
    for p in proposals:
        l = p["lead"]
        md.append(f"### {l['display_name']}  (`{l['id']}`)")
        md.append(f"- contact on file: **{l.get('primary_contact', '?')}**")
        md.append(f"- company: {l.get('company_name') or '—'}")
        md.append(f"- owner / stage: {l.get('owner') or '—'} / {l.get('stage') or '—'}")
        md.append("")
        md.append("| Rank | Email | Messages | Last seen |")
        md.append("|---|---|---|---|")
        for i, c in enumerate(p["candidates"], start=1):
            last = c["latest"].strftime("%Y-%m-%d") if c["latest"] else "—"
            md.append(f"| {i} | {c['email']} | {c['count']} | {last} |")
        md.append("")
    if no_match:
        md.append(f"## No matches found for {len(no_match)} lead(s)")
        md.append("")
        md.append("These leads have a named contact but no matching Gmail "
                    "history. Either the contact is not yet emailing you, or "
                    "their email comes through a different account / domain "
                    "filter. Add manually if known.")
        md.append("")
        for l in no_match:
            md.append(f"- `{l['id']}` — {l['display_name']} "
                        f"(contact: {l.get('primary_contact', '?')})")
        md.append("")

    if args.dry_run:
        print()
        print("\n".join(md))
    else:
        out_path = vault / "_Inbox" / f"{today}-lead-email-proposals.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(md))
        print(f"\nwrote: {out_path}")

    print(f"proposals:  {len(proposals)}")
    print(f"no match:   {len(no_match)}")
    print(f"api errors: {api_errors}")

    emit_telemetry(SCRIPT_NAME, outcome="success" if not api_errors else "partial_failure",
                   leads_mined=len(leads),
                   proposals=len(proposals),
                   no_match=len(no_match),
                   api_errors=api_errors,
                   accounts_used=len(svcs),
                   since_days=args.since_days,
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
