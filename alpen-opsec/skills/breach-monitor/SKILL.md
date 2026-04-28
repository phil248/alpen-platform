---
name: breach-monitor
description: Check Have I Been Pwned and similar feeds daily for any email/handle the principal owns. Surface new breaches with affected vendor + recommended action. Use as part of daily standup or on-demand.
---

# breach-monitor

## Status: stub (v0.1)

## Intent

Detect when one of the principal's accounts appears in a credential dump or breach disclosure, within hours of the public feed updating. Recommend the immediate action (rotate password, enable MFA, freeze credit, etc.).

## Inputs

- `~/.local/state/alpen/sqlite/account-inventory.db` — list of principal's emails / handles
- HIBP API (https://haveibeenpwned.com/API/v3) — k-anonymized breach lookup
- (Optional) commercial feeds (DeHashed, Intelligence X) for higher-recall

## Outputs

- `${VAULT}/HFO/OPSEC/Breach-Log/YYYY-MM-DD-breaches.md` if any new breach detected
- Telegram DM or Gmail draft to principal with recommended action
- Updated `account-inventory.db` row marking account as `breach_status=detected_<date>`

## Privacy

HIBP supports k-anonymity hash prefix lookups — full email is never sent over the wire. Use this mode exclusively. Never POST raw emails to any third-party API.

## v0.1 limitation

HIBP free tier only (1 req/sec). Sufficient for ~20 emails/handles checked daily. No commercial feeds wired.
