---
name: mcp-key-rotator
description: Quarterly rotation of API tokens and OAuth refresh tokens for connected MCP servers. Identifies tokens older than 90 days, walks the principal through the rotation UI per provider. Use quarterly or when a connected vendor announces a breach.
---

# mcp-key-rotator

## Status: stub (v0.1)

## Intent

Most MCP integrations use long-lived OAuth refresh tokens that, once granted, persist indefinitely. This is convenient and exactly the wrong security posture. Force a quarterly rotation cycle, and provide an interactive walkthrough for each provider's rotation UI.

## Inputs

- `~/.claude.json` — MCP server registration (per-tenant)
- `~/Winnie/config/scheduled.settings.json` — scheduled-task MCP config
- Principal's password manager (for new credentials going in)

## Outputs

- `${VAULT}/HFO/OPSEC/Audits/YYYY-Q<N>-mcp-rotation.md` — rotation log
- Updated MCP configs (re-OAuth where applicable)
- Diff of which servers were rotated vs. skipped

## Rotation criteria

- API token / OAuth refresh > 90 days since issued
- Vendor has had a security incident in the past quarter
- Principal asked for an out-of-cycle rotation (post-incident, post-departure)

## Interactive walkthrough (v0.1)

Per provider, this SKILL knows:
- Where in the vendor UI to revoke + reissue
- What scopes to grant on re-OAuth
- Whether the vendor supports CLI-based rotation (most don't)
- How to update `~/.claude.json` and `scheduled.settings.json` after re-OAuth

## v0.1 limitation

Manual walkthrough per provider; no automated rotation. Most vendors don't expose programmatic rotation. v0.2 candidate: machine-readable rotation contracts per provider.
