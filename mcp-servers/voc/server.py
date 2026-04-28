#!/usr/bin/env python3
"""Alpen Platform Voice-of-Customer MCP server.

Exposes structured access to mined VoC signals from meeting transcripts.
Backing store: ~/.local/state/alpen/sqlite/voc-signals.db (populated by
alpen-platform/bin/voc-extract.py).

Tools:
  voc_search(query?, signal_type?, severity?, account?, since?, limit=10)
    Substring + filter search across signals. Returns recent matches first.
  voc_account(account)
    All open (unresolved) signals attributed to a specific account/company.
  voc_recent(limit=10)
    Most recent unresolved signals across all accounts, severity-ordered.
  voc_summary()
    High-level rollup: counts by type, by severity, by account.
  voc_resolve(signal_id, resolution)
    Mark a signal resolved with a short note.

Registration (run AFTER first voc-extract.py run created the DB):
  claude mcp add --scope user voc \
    "/Users/philhoward/Winnie/alpen-platform/mcp-servers/voc/.venv/bin/python" \
    "/Users/philhoward/Winnie/alpen-platform/mcp-servers/voc/server.py"

  Plus add to ~/Winnie/config/scheduled.settings.json:mcpServers per
  HFO-mcp-registration.md gotcha (interactive + scheduled both need it).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

VOC_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/voc-signals.db"))

mcp = FastMCP("alpen-voc")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    if not VOC_DB.is_file():
        raise FileNotFoundError(
            f"voc-signals.db not found at {VOC_DB}. Run "
            f"alpen-platform/bin/voc-extract.py --tenant <id> --backfill first."
        )
    c = sqlite3.connect(VOC_DB)
    c.row_factory = sqlite3.Row
    return c


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    return {k: r[k] for k in r.keys()}


VALID_TYPES = {
    "expansion", "objection", "churn_risk", "feedback", "competitive",
    "expansion_blocker", "commitment", "ask", "praise", "risk", "opportunity",
}
VALID_SEV = {"low", "medium", "high", "critical"}


# ──────────────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def voc_search(
    query: str = "",
    signal_type: str = "",
    severity: str = "",
    account: str = "",
    since: str = "",
    include_resolved: bool = False,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search VoC signals with filters.

    Args:
        query: substring matched against description + evidence (case-insensitive)
        signal_type: filter to one type (expansion | objection | churn_risk | ...)
        severity: filter to one level (low | medium | high | critical)
        account: filter to a specific account/company
        since: ISO date (YYYY-MM-DD); only meetings on/after this date
        include_resolved: include signals already marked resolved
        limit: max results (default 10, max 100)

    Returns matching signals as a list of dicts (most recent meeting first,
    severity-ordered within meeting).
    """
    limit = max(1, min(int(limit), 100))
    where = []
    args: list[Any] = []

    if query:
        where.append("(s.description LIKE ? OR s.evidence LIKE ?)")
        args.extend([f"%{query}%", f"%{query}%"])
    if signal_type:
        if signal_type not in VALID_TYPES:
            return [{"error": f"signal_type must be one of {sorted(VALID_TYPES)}"}]
        where.append("s.signal_type = ?")
        args.append(signal_type)
    if severity:
        if severity not in VALID_SEV:
            return [{"error": f"severity must be one of {sorted(VALID_SEV)}"}]
        where.append("s.severity = ?")
        args.append(severity)
    if account:
        where.append("(s.attributed_to_account = ? OR t.client_name = ?)")
        args.extend([account, account])
    if since:
        try:
            datetime.fromisoformat(since)
        except ValueError:
            return [{"error": f"since must be ISO date YYYY-MM-DD, got {since!r}"}]
        where.append("t.meeting_date >= ?")
        args.append(since)
    if not include_resolved:
        where.append("s.resolved_at IS NULL")

    sql = """
        SELECT s.id, s.signal_type, s.severity, s.description, s.evidence,
               s.topic, s.attributed_to_account, s.routed_to_dept, s.resolved_at,
               t.meeting_date, t.meeting_title, t.client_name, t.entity_id, t.vault_path
        FROM signal s
        JOIN transcript t ON t.id = s.transcript_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += """
        ORDER BY t.meeting_date DESC,
                 CASE s.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                                 WHEN 'medium' THEN 3 ELSE 4 END
        LIMIT ?
    """
    args.append(limit)

    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    return [_row_to_dict(r) for r in rows]


@mcp.tool()
def voc_account(account: str, include_resolved: bool = False) -> list[dict[str, Any]]:
    """All signals attributed to a specific account/company.

    Use case: pre-call brief for a CCG meeting with WebMD — get every signal
    we have on file across all transcripts mentioning that account.

    Args:
        account: account name (e.g., "WebMD", "Roche", "Eli Lilly")
        include_resolved: include resolved signals (default: only open)
    """
    if not account:
        return [{"error": "account is required"}]
    return voc_search(account=account, include_resolved=include_resolved, limit=100)


@mcp.tool()
def voc_recent(limit: int = 10, severity_min: str = "medium") -> list[dict[str, Any]]:
    """Most recent unresolved signals at or above the given severity.

    The Sales/CS action surface for "what should I act on this morning?"

    Args:
        limit: max results (default 10)
        severity_min: minimum severity to include (low | medium | high | critical)
    """
    sev_rank = {"low": 4, "medium": 3, "high": 2, "critical": 1}
    if severity_min not in sev_rank:
        return [{"error": f"severity_min must be one of {sorted(sev_rank)}"}]
    cutoff = sev_rank[severity_min]

    with _conn() as c:
        rows = c.execute("""
            SELECT s.id, s.signal_type, s.severity, s.description,
                   s.attributed_to_account, t.meeting_date, t.meeting_title, t.entity_id
            FROM signal s
            JOIN transcript t ON t.id = s.transcript_id
            WHERE s.resolved_at IS NULL
              AND CASE s.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                                  WHEN 'medium' THEN 3 ELSE 4 END <= ?
            ORDER BY
              t.meeting_date DESC,
              CASE s.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                              WHEN 'medium' THEN 3 ELSE 4 END
            LIMIT ?
        """, (cutoff, max(1, min(int(limit), 100)))).fetchall()
    return [_row_to_dict(r) for r in rows]


@mcp.tool()
def voc_summary() -> dict[str, Any]:
    """High-level VoC rollup. Use to answer 'what's the state of customer signal?'.

    Returns counts grouped by signal_type, severity, and top accounts —
    plus the most recent transcript date and total signal volume.
    """
    with _conn() as c:
        by_type = [_row_to_dict(r) for r in c.execute("""
            SELECT signal_type, COUNT(*) AS n FROM signal WHERE resolved_at IS NULL
            GROUP BY signal_type ORDER BY n DESC
        """).fetchall()]
        by_severity = [_row_to_dict(r) for r in c.execute("""
            SELECT severity, COUNT(*) AS n FROM signal WHERE resolved_at IS NULL
            GROUP BY severity
            ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                                   WHEN 'medium' THEN 3 ELSE 4 END
        """).fetchall()]
        top_accounts = [_row_to_dict(r) for r in c.execute("""
            SELECT COALESCE(s.attributed_to_account, t.client_name) AS account,
                   COUNT(*) AS signals,
                   MAX(t.meeting_date) AS most_recent
            FROM signal s JOIN transcript t ON t.id = s.transcript_id
            WHERE s.resolved_at IS NULL
              AND COALESCE(s.attributed_to_account, t.client_name) IS NOT NULL
            GROUP BY account
            ORDER BY signals DESC LIMIT 10
        """).fetchall()]
        meta = c.execute("""
            SELECT COUNT(*) AS transcripts,
                   COUNT(DISTINCT entity_id) AS entities,
                   MAX(meeting_date) AS most_recent_meeting,
                   MAX(extracted_at) AS most_recent_extraction
            FROM transcript
        """).fetchone()
        signal_total = c.execute("SELECT COUNT(*) FROM signal").fetchone()[0]
        unresolved = c.execute("SELECT COUNT(*) FROM signal WHERE resolved_at IS NULL").fetchone()[0]

    return {
        "transcripts_processed": meta["transcripts"],
        "entities_seen": meta["entities"],
        "most_recent_meeting": meta["most_recent_meeting"],
        "most_recent_extraction": meta["most_recent_extraction"],
        "signal_total": signal_total,
        "signal_unresolved": unresolved,
        "by_type": by_type,
        "by_severity": by_severity,
        "top_accounts": top_accounts,
    }


@mcp.tool()
def voc_resolve(signal_id: int, resolution: str) -> dict[str, Any]:
    """Mark a signal as resolved with a short note.

    Use after acting on a signal — sending the follow-up, closing the loop,
    qualifying out, etc. Resolved signals are excluded from voc_recent /
    voc_search by default.

    Args:
        signal_id: the integer id of the signal
        resolution: short note describing what was done (max 240 chars)
    """
    if not resolution:
        return {"error": "resolution is required"}
    with _conn() as c:
        cur = c.execute(
            "UPDATE signal SET resolved_at = datetime('now'), resolution = ? "
            "WHERE id = ? AND resolved_at IS NULL",
            (resolution[:240], int(signal_id)),
        )
        c.commit()
        if cur.rowcount == 0:
            existing = c.execute("SELECT id, resolved_at FROM signal WHERE id = ?", (int(signal_id),)).fetchone()
            if existing is None:
                return {"error": f"signal {signal_id} not found"}
            return {"error": f"signal {signal_id} already resolved at {existing['resolved_at']}"}
    return {"resolved": signal_id, "resolution": resolution[:240]}


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
