---
name: password-hygiene
description: Quarterly audit of password manager — flag reused passwords, weak passwords, accounts with no MFA, dormant accounts, expired tokens. Use quarterly or after a breach event. Reads from 1Password CLI or Bitwarden CLI.
---

# password-hygiene

## Status: stub (v0.1)

## Intent

Detect rot in the principal's credential hygiene before it becomes a breach. Audit four dimensions: password reuse, password strength, MFA presence, account staleness.

## Inputs

- `op` (1Password CLI) or `bw` (Bitwarden CLI) — reads vault metadata only (never plaintext passwords)
- `~/.local/state/alpen/sqlite/account-inventory.db` — for cross-reference

## Outputs

- `${VAULT}/HFO/OPSEC/Audits/YYYY-Q<N>-password-audit.md` — audit report
- Per-account remediation tasks routed to `productivity/task-management` or `email-triage`

## What gets flagged

- Reused password across 2+ accounts (any reuse with a tier-1 service is critical)
- Password strength < 60 bits entropy
- Tier-1 account (banking, email, cloud, identity) with no MFA enabled
- Account unused > 12 months (candidate for deletion)
- API token / OAuth refresh > 90 days old

## v0.1 limitation

Reads metadata only. Cannot see actual passwords (good — keeps the principal's vault sealed). Surface area limited to what `op` / `bw` CLIs expose.
