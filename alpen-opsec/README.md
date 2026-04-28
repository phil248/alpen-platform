# alpen-opsec

Operational security for solo principals and family offices. Closes the gap that no upstream Anthropic plugin addresses: managing digital attack surface for someone whose business + personal + family data lives across dozens of accounts and integrations.

## Status

**v0.1 — scaffold only.** SKILL stubs document intent and the data each touches. Real coverage builds incrementally.

## When to use

| Capability | When |
|---|---|
| `breach-monitor` | Daily — checks Have I Been Pwned + similar feeds for any of the principal's known emails / handles |
| `password-hygiene` | Quarterly audit — flags reused passwords, expired credentials, unused accounts |
| `digital-footprint-scanner` | On-demand — what does the open web know about the principal? |
| `mcp-key-rotator` | Quarterly — rotates API tokens / OAuth refresh tokens for connected MCP servers |

## Data stores

- `~/.local/state/alpen/sqlite/account-inventory.db` — every account the principal holds (vendor, email, last-rotated)
- `${VAULT}/HFO/OPSEC/` — encrypted at rest (via `age` per architecture spec); never gitignored-but-readable
- RAG kind `hfo-opsec` (private, ACL-gated; never logged to telemetry summaries)

## Privacy posture

This plugin handles the principal's most sensitive data. Hard rules:
- Vault path `HFO/OPSEC/` MUST be encrypted at rest
- RAG kind `hfo-opsec` MUST be excluded from telemetry summaries
- No values from this plugin EVER appear in invocation logs (tenant config `telemetry.privacy.excluded_kinds` enforces)
- `account-inventory.db` SHOULD live in encrypted home dir (FileVault on macOS minimum)

## v0.1 → v0.2 backlog

1. HIBP API integration for `breach-monitor` (free tier sufficient for solo principal)
2. Read 1Password CLI / Bitwarden CLI for `password-hygiene` source data
3. `digital-footprint-scanner` — composes with `alpen-deep-research/client-content-inventory --subject <principal-name>` (DD on yourself = OPSEC audit)
4. `mcp-key-rotator` — automate rotation flow per provider (most need manual UI today)
