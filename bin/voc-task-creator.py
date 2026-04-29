#!/usr/bin/env python3
"""For each unresolved high-or-critical VoC signal, create a Google Task.

Closes the loop: VoC signals get extracted from Plaud transcripts and sit
in voc-signals.db. Until now they were only surfaced in standup section
8c. This script turns each one into an actionable Task on personal-phil's
@default list, due today, so it appears in the standup's tasks-due-today
section.

Idempotency: tracks task_id + task_created_at on the signal row.
Re-running won't duplicate tasks for already-tasked signals. If a signal
is later marked resolved (resolved_at set), it stops appearing as a
candidate even if task_id is missing (someone handled it without going
through this flow).

Schema migration: adds task_id + task_created_at columns to signal table
if missing (idempotent ALTER TABLE).

Usage:
  voc-task-creator.py --tenant phil-howard
  voc-task-creator.py --tenant phil-howard --severity critical    # critical only
  voc-task-creator.py --tenant phil-howard --max 5                # cap how many tasks per run
  voc-task-creator.py --tenant phil-howard --dry-run
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
SCRIPT_NAME = "voc-task-creator"
VOC_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/voc-signals.db"))
GW_TOKENS_DIR = Path(os.path.expanduser("~/Winnie/mcp-servers/google-workspace/tokens"))


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def ensure_columns(conn: sqlite3.Connection) -> None:
    """Add task_id + task_created_at columns to signal table if missing."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(signal)").fetchall()}
    if "task_id" not in cols:
        conn.execute("ALTER TABLE signal ADD COLUMN task_id TEXT")
    if "task_created_at" not in cols:
        conn.execute("ALTER TABLE signal ADD COLUMN task_created_at DATETIME")
    conn.commit()


def find_candidates(conn: sqlite3.Connection, min_severity: str, limit: int) -> list[dict]:
    severities = {
        "critical": ["critical"],
        "high": ["critical", "high"],
        "medium": ["critical", "high", "medium"],
    }[min_severity]
    placeholders = ",".join("?" for _ in severities)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"""
        SELECT s.id, s.signal_type, s.severity, s.description, s.evidence,
               s.attributed_to_account, s.routed_to_dept,
               t.client_name, t.meeting_date, t.entity_id, t.vault_path
        FROM signal s JOIN transcript t ON t.id = s.transcript_id
        WHERE s.resolved_at IS NULL
          AND s.task_id IS NULL
          AND s.severity IN ({placeholders})
        ORDER BY CASE s.severity
                   WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                   WHEN 'medium' THEN 3 ELSE 4
                 END,
                 t.meeting_date DESC
        LIMIT ?
    """, [*severities, limit]).fetchall()
    return [dict(r) for r in rows]


def gw_tasks_service(account: str):
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
        sys.exit(f"error: token for {account!r} not found")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            sys.exit(f"error: token for {account!r} expired/invalid")
    return build("tasks", "v1", credentials=creds, cache_discovery=False)


def make_task(svc, signal: dict, due: date) -> str | None:
    sev_badge = {"critical": "🔴 CRITICAL", "high": "🟠 high"}.get(signal["severity"], signal["severity"])
    account = signal.get("attributed_to_account") or signal.get("client_name") or "?"
    title = f"VoC [{sev_badge}] {signal['signal_type']}: {account} — {(signal['description'] or '')[:60]}"
    notes = (
        f"Type: {signal['signal_type']}\n"
        f"Severity: {signal['severity']}\n"
        f"Account: {account}\n"
        f"Routed: {signal.get('routed_to_dept') or '—'}\n"
        f"Meeting: {signal.get('meeting_date') or '—'}\n"
        f"Source: {signal.get('vault_path') or '—'}\n\n"
        f"Description:\n{signal['description']}\n\n"
        f"Evidence:\n{(signal.get('evidence') or '—')[:400]}\n\n"
        "Mark resolved in voc-signals.db once acted on (sets resolved_at;\n"
        "this script will then stop surfacing it)."
    )
    body = {
        "title": title[:1024],
        "notes": notes[:8000],
        "due": datetime.combine(due, datetime.min.time()).strftime("%Y-%m-%dT00:00:00Z"),
    }
    try:
        result = svc.tasks().insert(tasklist="@default", body=body).execute()
        return result.get("id")
    except Exception as e:
        print(f"  ! task insert failed: {e}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--severity", choices=["critical", "high", "medium"], default="high",
                        help="Minimum severity (default: high — catches critical + high)")
    parser.add_argument("--max", type=int, default=10,
                        help="Max tasks created per run (default: 10)")
    parser.add_argument("--task-account", default="personal-phil")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not VOC_DB.is_file():
        sys.exit(f"error: voc-signals.db not found at {VOC_DB}; run voc-extract.py first")

    start = time.time()
    conn = sqlite3.connect(VOC_DB)
    ensure_columns(conn)
    candidates = find_candidates(conn, args.severity, args.max)

    print(f"=== {SCRIPT_NAME} (tenant={args.tenant}) ===")
    print(f"min severity:   {args.severity}")
    print(f"candidates:     {len(candidates)} (cap {args.max})")
    if not candidates:
        print("nothing to task")
        emit_telemetry(SCRIPT_NAME, outcome="success", candidates=0, created=0,
                       severity=args.severity,
                       duration_seconds=round(time.time() - start, 2))
        conn.close()
        return 0

    if args.dry_run:
        for c in candidates:
            sev = c["severity"]
            acct = c.get("attributed_to_account") or c.get("client_name") or "?"
            print(f"  [DRY] [{sev}] {c['signal_type']:18s} {acct:20s} — {(c['description'] or '')[:60]}")
        emit_telemetry(SCRIPT_NAME, outcome="success", dry_run=True,
                       candidates=len(candidates), created=0,
                       severity=args.severity,
                       duration_seconds=round(time.time() - start, 2))
        conn.close()
        return 0

    svc = gw_tasks_service(args.task_account)
    today = date.today()
    created = 0
    failed = 0
    for c in candidates:
        task_id = make_task(svc, c, today)
        if not task_id:
            failed += 1
            continue
        conn.execute(
            "UPDATE signal SET task_id = ?, task_created_at = ? WHERE id = ?",
            (task_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), c["id"]),
        )
        conn.commit()
        created += 1
        sev = c["severity"]
        acct = c.get("attributed_to_account") or c.get("client_name") or "?"
        print(f"  [{sev}] {acct:20s} -> task {task_id}")
    conn.close()

    print(f"\ncreated: {created}, failed: {failed}")

    emit_telemetry(SCRIPT_NAME,
                   outcome="success" if not failed else "partial_failure",
                   candidates=len(candidates),
                   created=created,
                   failed=failed,
                   severity=args.severity,
                   duration_seconds=round(time.time() - start, 2))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
