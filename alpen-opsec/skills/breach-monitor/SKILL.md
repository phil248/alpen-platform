---
name: breach-monitor
description: Check Have I Been Pwned and similar feeds daily for any email/handle the principal owns. Surface new breaches with affected vendor + recommended action. Use as part of daily standup or on-demand.
---

# breach-monitor

## Status: framework live (v0.1); requires HIBP_API_KEY to activate

## v0.1 implementation

`alpen-opsec/bin/breach-monitor.py --tenant <id>` — reads
tenant.principals[].accounts[] (kind=gmail) for monitored emails, calls
HIBP `/api/v3/breachedaccount/{email}` per address with rate limiting,
diffs against `~/.local/state/alpen/opsec/breach-state.json`, surfaces
ONLY new breaches in the daily report.

Output: `$VAULT/HFO/OPSEC/Breach-Log/YYYY-MM-DD-breaches.md`

Scheduled daily at 06:50 AM via `io.howardfamily.alpen.breach-monitor`,
run by `~/Winnie/bin/alpen-breach-monitor.sh` (sources
`~/Winnie/config/environment` so the gitignored HIBP_API_KEY is picked
up without leaking into plist or git).

**Activation**: HIBP requires a paid subscription ($3.95/mo). Set
`export HIBP_API_KEY=xxx` in `~/Winnie/config/environment` to activate.
Until set, the daily firing exits 0 with a "skipped" message.

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
