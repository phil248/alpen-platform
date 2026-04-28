# alpen-voc MCP server

FastMCP server exposing Voice-of-Customer signals mined from meeting transcripts.

## Backing store

`~/.local/state/alpen/sqlite/voc-signals.db` (per `feedback_alpen_storage_patterns.md` tier 4)

## Populated by

`alpen-platform/bin/voc-extract.py --tenant <id>` (interactive or backfill)

## Tools

| Tool | Purpose |
|---|---|
| `voc_search` | Substring + filter search (signal_type, severity, account, since) |
| `voc_account` | Pre-call brief: every signal we have on a given account |
| `voc_recent` | Action surface: most recent unresolved signals at minimum severity |
| `voc_summary` | Rollup by type / severity / top accounts |
| `voc_resolve` | Mark a signal resolved with a note |

## Registration

Already registered via:
```
claude mcp add --scope user voc \
  ~/Winnie/alpen-platform/mcp-servers/voc/.venv/bin/python \
  ~/Winnie/alpen-platform/mcp-servers/voc/server.py
```

Plus added to `~/Winnie/config/scheduled.settings.json:mcpServers.voc` for scheduled-task access.

## Why both?

Per `HFO-mcp-registration.md`: interactive CLI ignores `~/.claude/settings.json:mcpServers`; scheduled agents only honor `--settings <file>:mcpServers`. Register in both for full coverage.
