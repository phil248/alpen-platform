# alpen-ip-watcher MCP server

FastMCP server for trademark + patent monitoring. v0.1 implements the
schema + tooling for trademark watch lists and status-change detection.

## v0.1 status

- ✓ Schema + persistence + status-change detection working
- ✓ MCP tools registered + functional
- ⚠ Live USPTO TSDR fetch blocked — endpoint returns 403 to non-browser clients

## v0.2 backlog

- Wire live USPTO Open Data Portal (https://developer.uspto.gov/api-catalog)
  with API key
- TSDR JSON endpoint with proper Accept headers
- PEDS for patent equivalents
- Periodic poller (`bin/ip-watch-poll.py`) running active marks daily

## Tools

| Tool | Purpose |
|---|---|
| `ip_watch_status` | Live fetch (currently blocked); returns parsed TSDR data + persists snapshot |
| `ip_watch_track` | Add a serial number to active watch list |
| `ip_watch_marks` | List tracked marks with last-known status |
| `ip_watch_events` | Status change events detected across watched marks |
| `ip_watch_review` | Mark a status event reviewed (act / dismiss) |

## Manual workflow (works today even with live fetch blocked)

If live TSDR fetch is unavailable, you can still maintain the watch list
manually by inserting rows directly:

```python
from server import _persist_snapshot, _ensure_db
conn = _ensure_db()
_persist_snapshot(conn, {
    "serial_number": "97123456",
    "mark_text": "EXAMPLE",
    "owner": "Example Co.",
    "status": "Live/Pending",
    "status_date": "2026-04-28",
    "filing_date": "2026-03-15",
})
conn.commit()
```

When you re-run `_persist_snapshot` with an updated `status` value, a
`status_event` row is automatically inserted and surfaced via
`ip_watch_events`.
