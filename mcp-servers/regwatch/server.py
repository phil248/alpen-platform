#!/usr/bin/env python3
"""Alpen Platform regulatory-watch MCP server (v0.1).

Wraps the Federal Register API (free, no auth required) as MCP tools.
v0.2 will add Regulations.gov + CourtListener.

Backing store: ~/.local/state/alpen/sqlite/regwatch.db (subscriptions + alerts)

Tools:
  regwatch_search(query, agency?, since?, per_page=10)
    Search Federal Register documents. Returns ranked recent matches.
    No auth required; rate-limited to 60/min by Federal Register.

  regwatch_alerts(unreviewed_only=True, limit=20)
    Show alerts already surfaced + persisted from prior searches/subscriptions.

  regwatch_subscribe(query, agencies?, notes?)
    Save a query as a recurring subscription. Doesn't auto-fire here —
    a scheduled task ({TODO} bin/regwatch-poll.py) runs subscriptions.

  regwatch_review(alert_id, decision, notes?)
    Mark an alert as relevant / irrelevant / act_on with a note.

  regwatch_subscriptions()
    List all active subscriptions.

Schedule (when wired): a regwatch-poll.py script runs subscriptions
once per business day, persisting any new matches to the alert table.
v0.1 of this server is read-only-ish + manual-search-driven.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

REGWATCH_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/regwatch.db"))
SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas" / "sql"
FED_REG = "https://www.federalregister.gov/api/v1"

mcp = FastMCP("alpen-regwatch")


def _ensure_db() -> sqlite3.Connection:
    REGWATCH_DB.parent.mkdir(parents=True, exist_ok=True)
    fresh = not REGWATCH_DB.is_file()
    conn = sqlite3.connect(REGWATCH_DB)
    if fresh:
        with (SCHEMAS_DIR / "regwatch.sql").open() as f:
            conn.executescript(f.read())
        conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


def _row(r: sqlite3.Row) -> dict[str, Any]:
    return {k: r[k] for k in r.keys()}


# ──────────────────────────────────────────────────────────────────────────────
# Federal Register API
# ──────────────────────────────────────────────────────────────────────────────

def _fed_reg_search(query: str, agency: str | None, since: str | None, per_page: int) -> list[dict]:
    """Search Federal Register; persist matches to alert table; return them."""
    params: dict[str, Any] = {
        "conditions[term]": query,
        "per_page": min(max(int(per_page), 1), 50),
        "order": "newest",
    }
    if agency:
        params["conditions[agencies][]"] = agency
    if since:
        params["conditions[publication_date][gte]"] = since
    try:
        r = httpx.get(f"{FED_REG}/documents.json", params=params, timeout=15.0)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return [{"error": f"federal_register fetch failed: {e}"}]

    results = []
    conn = _ensure_db()
    for doc in data.get("results", []):
        doc_number = doc.get("document_number") or ""
        title = doc.get("title", "")[:500]
        url = doc.get("html_url", "")
        pub = doc.get("publication_date", "")
        agencies = ", ".join(a.get("name", "") for a in doc.get("agencies", []) or [])
        abstract = doc.get("abstract", "") or ""
        # Persist (idempotent via UNIQUE)
        try:
            conn.execute("""
                INSERT INTO alert (source, external_id, title, agency, publication_date, url, abstract)
                VALUES ('federal_register', ?, ?, ?, ?, ?, ?)
            """, (doc_number, title, agencies[:120], pub, url, abstract[:2000]))
        except sqlite3.IntegrityError:
            pass  # already in DB
        results.append({
            "document_number": doc_number,
            "title": title,
            "agency": agencies,
            "publication_date": pub,
            "url": url,
            "abstract": abstract[:400],
            "type": doc.get("type"),
        })
    conn.commit()
    conn.close()
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def regwatch_search(
    query: str,
    agency: str = "",
    since: str = "",
    per_page: int = 10,
) -> list[dict[str, Any]]:
    """Search the Federal Register for recent regulatory documents.

    Args:
        query: search term (e.g., "workplace mental health", "AI safety")
        agency: optional agency name filter (e.g., "Department of Health and Human Services")
        since: optional ISO date (YYYY-MM-DD); only docs published on/after
        per_page: max results (1-50, default 10)

    Returns matched documents (newest first). Side effect: persists each
    match into the local alert table for later review via regwatch_alerts().
    """
    if not query:
        return [{"error": "query is required"}]
    if since:
        try:
            datetime.fromisoformat(since)
        except ValueError:
            return [{"error": f"since must be YYYY-MM-DD; got {since!r}"}]
    return _fed_reg_search(query, agency or None, since or None, per_page)


@mcp.tool()
def regwatch_alerts(unreviewed_only: bool = True, limit: int = 20) -> list[dict[str, Any]]:
    """List alerts already surfaced + persisted in the local DB.

    Args:
        unreviewed_only: filter to alerts not yet reviewed (default True)
        limit: max results
    """
    conn = _ensure_db()
    if unreviewed_only:
        rows = conn.execute("SELECT * FROM v_alerts_unreviewed LIMIT ?", (max(1, min(int(limit), 100)),)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, source, agency, publication_date, title, url, abstract, "
            "reviewed_at, review_decision FROM alert "
            "ORDER BY publication_date DESC, surfaced_at DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    conn.close()
    return [_row(r) for r in rows]


@mcp.tool()
def regwatch_subscribe(query: str, agencies: str = "", notes: str = "") -> dict[str, Any]:
    """Save a query as a recurring subscription. Does NOT auto-fire here —
    a scheduled poller (regwatch-poll.py — TODO v0.2) runs subscriptions
    once per business day.

    Args:
        query: the search term
        agencies: optional comma-separated agency filter
        notes: free-text notes on what this subscription is watching for
    """
    if not query:
        return {"error": "query is required"}
    conn = _ensure_db()
    cur = conn.execute(
        "INSERT INTO subscription (query, source, agencies, notes) "
        "VALUES (?, 'federal_register', ?, ?)",
        (query, agencies or None, notes or None),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"subscribed": new_id, "query": query, "agencies": agencies, "source": "federal_register"}


@mcp.tool()
def regwatch_subscriptions() -> list[dict[str, Any]]:
    """List active subscriptions."""
    conn = _ensure_db()
    rows = conn.execute(
        "SELECT id, query, source, agencies, notes, created_at FROM subscription WHERE active = 1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [_row(r) for r in rows]


@mcp.tool()
def regwatch_review(alert_id: int, decision: str, notes: str = "") -> dict[str, Any]:
    """Mark an alert with a review decision.

    Args:
        alert_id: integer id of the alert
        decision: "relevant" | "irrelevant" | "act_on"
        notes: free-text note
    """
    if decision not in {"relevant", "irrelevant", "act_on"}:
        return {"error": "decision must be relevant | irrelevant | act_on"}
    conn = _ensure_db()
    cur = conn.execute(
        "UPDATE alert SET reviewed_at = datetime('now'), review_decision = ?, notes = ? "
        "WHERE id = ? AND reviewed_at IS NULL",
        (decision, notes[:500] if notes else None, int(alert_id)),
    )
    conn.commit()
    if cur.rowcount == 0:
        existing = conn.execute("SELECT id, reviewed_at FROM alert WHERE id = ?", (int(alert_id),)).fetchone()
        conn.close()
        if not existing:
            return {"error": f"alert {alert_id} not found"}
        return {"error": f"alert {alert_id} already reviewed at {existing['reviewed_at']}"}
    conn.close()
    return {"reviewed": alert_id, "decision": decision}


if __name__ == "__main__":
    mcp.run()
