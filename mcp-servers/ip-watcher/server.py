#!/usr/bin/env python3
"""Alpen Platform IP-watcher MCP server (v0.1).

Wraps USPTO Trademark Status & Document Retrieval (TSDR) — the public XML
endpoint that returns full status for a trademark by serial number. v0.2
will add patent monitoring via PEDS and similar-mark search via TESS.

Backing store: ~/.local/state/alpen/sqlite/ip-watch.db

Tools:
  ip_watch_status(serial_number)
    Live USPTO TSDR fetch for one trademark by serial number. Returns the
    current status + dates. Persists snapshot to local DB for change
    detection on subsequent calls.

  ip_watch_track(serial_number, notes?)
    Add a serial number to the watch list. Performs initial fetch.

  ip_watch_marks(active_only=True)
    List tracked marks (with last-known status).

  ip_watch_events(unreviewed_only=True, limit=20)
    Status change events detected across watched marks.

  ip_watch_review(event_id, decision, notes?)
    Mark a status event as reviewed (act / dismiss).
"""

from __future__ import annotations

import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/ip-watch.db"))
SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas" / "sql"
TSDR_URL = "https://tsdr.uspto.gov/ts/cd/casestatus/sn{sn}/info.xml"
# NOTE v0.1 limitation: USPTO TSDR direct XML endpoint returns 403 to non-browser
# clients. v0.2 should switch to one of:
#   1. USPTO Open Data Portal (https://developer.uspto.gov/api-catalog) with a
#      registered API key.
#   2. The newer TSDR JSON endpoint with appropriate Accept headers.
#   3. Patent Examination Data System (PEDS) for patent equivalents.
# Tools below still work for manual-entry tracking + status_event detection.

mcp = FastMCP("alpen-ip-watcher")


def _ensure_db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    fresh = not DB.is_file()
    conn = sqlite3.connect(DB)
    if fresh:
        with (SCHEMAS_DIR / "ip-watch.sql").open() as f:
            conn.executescript(f.read())
        conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


def _row(r: sqlite3.Row) -> dict[str, Any]:
    return {k: r[k] for k in r.keys()}


def _normalize_serial(sn: str) -> str | None:
    s = re.sub(r"[^\d]", "", str(sn))
    if not s or len(s) != 8:
        return None
    return s


def _fetch_tsdr(serial: str) -> dict[str, Any] | None:
    """Fetch USPTO TSDR XML for a serial; return key fields as dict, or None on error."""
    url = TSDR_URL.format(sn=serial)
    try:
        r = httpx.get(url, timeout=15.0, headers={
            "User-Agent": "alpen-ip-watcher/0.1 (https://alpentech.ai; phil@cognitivecapitalgroup.com)",
        })
        r.raise_for_status()
    except httpx.HTTPError as e:
        return {"_error": f"USPTO TSDR fetch failed: {e}"}
    try:
        # The XML uses namespaces; we use local-name() workarounds.
        root = ET.fromstring(r.text)
    except ET.ParseError as e:
        return {"_error": f"TSDR XML parse failed: {e}"}

    def find_text(elem, local_name: str) -> str | None:
        for child in elem.iter():
            if child.tag.split("}", 1)[-1] == local_name:
                return (child.text or "").strip() or None
        return None

    return {
        "serial_number":     find_text(root, "ApplicationNumberText") or serial,
        "mark_text":         find_text(root, "MarkVerbalElementText"),
        "owner":             find_text(root, "ContactPartyName") or find_text(root, "Name"),
        "status":            find_text(root, "MarkCurrentStatusExternalDescriptionText") or find_text(root, "MarkCurrentStatusCodeDescription"),
        "status_date":       find_text(root, "MarkCurrentStatusDate"),
        "filing_date":       find_text(root, "ApplicationDate"),
        "registration_date": find_text(root, "RegistrationDate"),
    }


def _persist_snapshot(conn: sqlite3.Connection, fetched: dict, watch_id: int | None = None) -> int | None:
    """Insert/update watched_mark row; emit status_event if status text changed."""
    sn = fetched.get("serial_number")
    if not sn:
        return None
    existing = conn.execute(
        "SELECT id, status, status_date FROM watched_mark WHERE serial_number = ?", (sn,)
    ).fetchone()
    if existing:
        prev_status = existing["status"]
        new_status = fetched.get("status")
        if new_status and new_status != prev_status:
            conn.execute("""
                INSERT INTO status_event (watched_mark_id, event_date, event_type, description)
                VALUES (?, ?, ?, ?)
            """, (existing["id"], fetched.get("status_date") or datetime.now().date().isoformat(),
                  "status_change", f"{prev_status!r} -> {new_status!r}"))
        conn.execute("""
            UPDATE watched_mark SET
              mark_text = COALESCE(?, mark_text),
              owner = COALESCE(?, owner),
              status = COALESCE(?, status),
              status_date = COALESCE(?, status_date),
              filing_date = COALESCE(?, filing_date),
              registration_date = COALESCE(?, registration_date),
              last_checked_at = datetime('now')
            WHERE id = ?
        """, (fetched.get("mark_text"), fetched.get("owner"),
              fetched.get("status"), fetched.get("status_date"),
              fetched.get("filing_date"), fetched.get("registration_date"),
              existing["id"]))
        return existing["id"]
    cur = conn.execute("""
        INSERT INTO watched_mark
          (serial_number, mark_text, owner, status, status_date, filing_date, registration_date,
           active, last_checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
    """, (sn, fetched.get("mark_text"), fetched.get("owner"),
          fetched.get("status"), fetched.get("status_date"),
          fetched.get("filing_date"), fetched.get("registration_date")))
    return cur.lastrowid


# ──────────────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def ip_watch_status(serial_number: str) -> dict[str, Any]:
    """Live USPTO TSDR fetch for one trademark serial number.

    Args:
        serial_number: 8-digit USPTO trademark serial number

    Returns the current TSDR record (mark text, owner, status, dates).
    Side effect: persists snapshot to local DB; if a previously-tracked
    mark has changed status, emits a status_event row.
    """
    sn = _normalize_serial(serial_number)
    if not sn:
        return {"error": f"invalid serial number {serial_number!r}; expected 8 digits"}
    fetched = _fetch_tsdr(sn)
    if not fetched or "_error" in fetched:
        return {"error": fetched.get("_error", "fetch failed")}
    conn = _ensure_db()
    _persist_snapshot(conn, fetched)
    conn.commit()
    conn.close()
    return fetched


@mcp.tool()
def ip_watch_track(serial_number: str, notes: str = "") -> dict[str, Any]:
    """Add a trademark to the watch list. Performs an initial fetch + persists.

    Args:
        serial_number: 8-digit USPTO trademark serial number
        notes: free-text notes describing why this is being tracked
    """
    sn = _normalize_serial(serial_number)
    if not sn:
        return {"error": f"invalid serial number {serial_number!r}"}
    fetched = _fetch_tsdr(sn)
    if not fetched or "_error" in fetched:
        return {"error": fetched.get("_error", "fetch failed")}
    conn = _ensure_db()
    new_id = _persist_snapshot(conn, fetched)
    if notes:
        conn.execute("UPDATE watched_mark SET notes = ? WHERE id = ?", (notes[:500], new_id))
    conn.commit()
    conn.close()
    return {"tracked": new_id, "serial_number": sn, "mark_text": fetched.get("mark_text"),
            "status": fetched.get("status")}


@mcp.tool()
def ip_watch_marks(active_only: bool = True) -> list[dict[str, Any]]:
    """List tracked marks with last-known status."""
    conn = _ensure_db()
    if active_only:
        rows = conn.execute("SELECT * FROM v_marks_active").fetchall()
    else:
        rows = conn.execute(
            "SELECT id, serial_number, mark_text, owner, status, status_date, "
            "filing_date, registration_date, active, last_checked_at "
            "FROM watched_mark ORDER BY status_date DESC NULLS LAST"
        ).fetchall()
    conn.close()
    return [_row(r) for r in rows]


@mcp.tool()
def ip_watch_events(unreviewed_only: bool = True, limit: int = 20) -> list[dict[str, Any]]:
    """Status change events detected across watched marks.

    Args:
        unreviewed_only: filter to events not yet reviewed (default True)
        limit: max results
    """
    conn = _ensure_db()
    if unreviewed_only:
        rows = conn.execute("SELECT * FROM v_unreviewed_events LIMIT ?",
                            (max(1, min(int(limit), 100)),)).fetchall()
    else:
        rows = conn.execute("""
            SELECT e.id, e.watched_mark_id, m.serial_number, m.mark_text,
                   e.event_date, e.event_type, e.description,
                   e.reviewed_at, e.reviewed_decision
            FROM status_event e JOIN watched_mark m ON m.id = e.watched_mark_id
            ORDER BY e.event_date DESC LIMIT ?
        """, (max(1, min(int(limit), 100)),)).fetchall()
    conn.close()
    return [_row(r) for r in rows]


@mcp.tool()
def ip_watch_review(event_id: int, decision: str, notes: str = "") -> dict[str, Any]:
    """Mark a status event as reviewed.

    Args:
        event_id: id of the status_event
        decision: "act" | "dismiss"
        notes: free-text rationale
    """
    if decision not in {"act", "dismiss"}:
        return {"error": "decision must be 'act' or 'dismiss'"}
    conn = _ensure_db()
    cur = conn.execute(
        "UPDATE status_event SET reviewed_at = datetime('now'), reviewed_decision = ? "
        "WHERE id = ? AND reviewed_at IS NULL",
        (decision, int(event_id)),
    )
    conn.commit()
    rc = cur.rowcount
    conn.close()
    if rc == 0:
        return {"error": f"event {event_id} not found or already reviewed"}
    return {"reviewed": event_id, "decision": decision}


if __name__ == "__main__":
    mcp.run()
