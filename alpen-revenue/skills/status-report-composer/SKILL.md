---
name: status-report-composer
description: Generate weekly status report for an active engagement. Reads engagements.db + this-week activity + the templates/default/status-report.md template. Writes one short report per engagement. Use weekly (e.g., Friday afternoon cron) or when user says "status report for X" or "draft the weekly for the BP engagement".
---

# status-report-composer

## When to invoke

- Scheduled: weekly Friday PM (e.g., 16:00) per active engagement
- When user says "status report for <client>" / "weekly for <engagement>"
- When an engagement misses 2 consecutive weeks (auto-recovery)

## Inputs

- `engagement_id` (required if running for one engagement) — leave blank to do all active
- `week_start` (optional, defaults to current Monday) — Monday date

## Workflow

### Phase 1: identify engagements

If `engagement_id` provided: just that one. Otherwise: all rows in `engagements.db` with status in (ACTIVE, AT_RISK, KICKOFF).

### Phase 2: load week context

For each engagement, load:
- This week's vault activity in `${VAULT}/Delivery/Engagements/<id>/`
- This week's `engagement_deliverable` status changes
- This week's `engagement_change_order` rows
- This week's `engagement_risk` rows (any new + any resolved)
- Last week's status report (for "next week" → "done this week" carry-forward)
- Hours used (from time-tracking source, if any — placeholder for now)

### Phase 3: synthesize

For each engagement, fill template variables:
- `{{week.tldr}}` — 1-2 sentence summary; prioritize: deliverable accepted > risk materialized > on-track
- `{{week.done_1..3}}` — top 3 done items (deliverable status changes, milestones)
- `{{week.in_flight_1..2}}` — deliverables in-progress
- `{{week.next_1..3}}` — next-week priorities (from open deliverables + carry-forward + scheduled milestones)
- `{{week.risk_1..2}}` — open risks at high/critical, with mitigation
- `{{week.ask_1..2}}` — what we need from the client this week

### Phase 4: write output

Path: `${VAULT}/Delivery/Engagements/<engagement-id>/Status-Reports/YYYY-MM-DD.md`

If a file for this week already exists: append a "## Update" section rather than overwrite.

### Phase 5: persist to engagements.db

Insert/update an `engagement_status_report` row:
- `week_start_date = <Monday>`
- `health_score`, `health_color` from synthesis
- `tldr` and `vault_path`

### Phase 6: voice-sweep

Per entity rules.

### Phase 7: report

Tell the user:
- Path to status report(s)
- Health score summary across all reported engagements
- Any AT_RISK or RED-health flags

## Telemetry

```bash
~/Winnie/bin/hfo-log \
  --skill status-report-composer \
  --event skill_completed \
  --outcome success \
  --engagements-reported <n> \
  --reports-written <n> \
  --health-red <n> \
  --health-yellow <n> \
  --health-green <n>
```

## Edge cases

| Situation | Behavior |
|---|---|
| Engagement has no activity this week | Still produce report; tldr = "Quiet week — next milestone <X>"; flag if 2+ quiet weeks |
| Engagement just kicked off | Status report formatted as "kickoff confirmation" rather than weekly |
| Multiple engagements for same client | Generate separate reports; don't merge |
| AT_RISK escalation needed | Add "ESCALATION REQUIRED" section + flag for principal review before sending |

## What this skill does NOT do

- Send the status report (it lands in vault; user reviews and sends via Gmail)
- Update budget tracking (separate skill)
- Reach out to client about specific items (separate outreach flow)
