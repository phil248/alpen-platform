# alpen-regwatch MCP server

FastMCP server wrapping the Federal Register API. Persists alerts to
`~/.local/state/alpen/sqlite/regwatch.db` for review.

## Tools

| Tool | Purpose |
|---|---|
| `regwatch_search` | Live search against Federal Register; persists matches |
| `regwatch_alerts` | List alerts already in local DB (unreviewed by default) |
| `regwatch_subscribe` | Save a query for recurring monitoring |
| `regwatch_subscriptions` | List active subscriptions |
| `regwatch_review` | Mark an alert relevant / irrelevant / act_on with notes |

## Sources (v0.1)

- Federal Register API (https://www.federalregister.gov/api/v1) — free, no auth, 60/min rate limit

## Sources (v0.2 backlog)

- Regulations.gov API
- CourtListener API (with optional API key for higher rate limits)
- HHS / FDA / OSHA agency-specific RSS feeds

## Scheduled poller (TODO v0.2)

A `bin/regwatch-poll.py` will run subscriptions once per business day,
persisting new matches into `alert`. Wire into launchd same pattern as
`alpen-regenerate-all`.
