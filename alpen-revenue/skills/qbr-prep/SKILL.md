---
name: qbr-prep
description: Prepare a Quarterly Business Review for an active engagement. Reads engagements.db (current quarter activity), VoC signals from the RAG store, and the templates/default/qbr-deck.md template. Produces a markdown deck that gets rendered to slides separately. Use quarterly per active engagement, or when user says "prep the QBR for X" or "draft the Q3 review for the Roche engagement".
---

# qbr-prep

## When to invoke

- Quarterly per active engagement (could be on a scheduled cron — e.g., 3rd Monday of last month of each quarter)
- When user says "prep QBR for <client>" / "draft quarterly review for <engagement>"
- When an engagement is approaching its renewal date (within 60 days) and no recent QBR exists

## Inputs

- `engagement_id` (required) — the engagement to review
- `quarter` (optional, defaults to "current") — Q1/Q2/Q3/Q4 + year
- `extra_themes` (optional) — themes user wants emphasized

## Workflow

### Phase 1: load engagement data

1. Load engagement row from `engagements.db` (must exist; fail loudly if not)
2. Load all `engagement_status_report` rows for the quarter
3. Load all `engagement_change_order` rows for the quarter
4. Load all `engagement_risk` rows (open + resolved this quarter)
5. Load all `engagement_deliverable` rows (status changes this quarter)

### Phase 2: pull VoC signals from RAG

Query the RAG store for kind `voc-signals`:
- Filter to this engagement's client
- Filter to date range = this quarter
- Group by signal type: expansion / objection / churn-risk / feedback

### Phase 3: pull metrics

Domain-specific to the engagement:
- Tier 1: platform usage (skills run / week, automations active)
- Tier 2 / 3: hours used vs. budget, deliverables completed vs. planned, milestone achievement

These come from `engagements.db` summary plus telemetry (`invocations.jsonl` summary).

### Phase 4: render

Load `templates/default/qbr-deck.md` (or entity override if exists). Resolve `{{quarter.*}}`, `{{deal.*}}`, `{{next_quarter.*}}` variables.

Most variables are computed:
- `{{quarter.objective_N}}` from the prior QBR's `next_quarter.objective_N`
- `{{quarter.metric_N_curr}}` from this quarter's data
- `{{quarter.metric_N_prev}}` from prior quarter's data
- `{{next_quarter.action_N}}` synthesized from VoC signals + engagement status

For the synthesis (next_quarter recommendations): use Sonnet-class model. Frame each recommendation as: "Action X, owned by Y, because [VoC signal Z + engagement metric Q]."

### Phase 5: write output

Path: `${VAULT}/CS/QBRs/<engagement-id>-<quarter>.md`

### Phase 6: voice-sweep

If entity has `brand.no_em_dash: true`:
```bash
~/Winnie/bin/voice-sweep.sh "${VAULT}/CS/QBRs/<engagement-id>-<quarter>.md"
```

### Phase 7: report

Tell the user:
- Path to the rendered deck
- Engagement health summary (score / color)
- Top 3 next-quarter actions recommended
- Renewal date (if within 60 days, flag as urgent)

## Telemetry

```bash
~/Winnie/bin/hfo-log \
  --skill qbr-prep \
  --event skill_completed \
  --outcome success \
  --engagement-id <id> \
  --quarter <Q1-2026> \
  --voc-signals <n> \
  --next-quarter-actions <n> \
  --voice-sweep <pass|fail|skipped>
```

## Edge cases

| Situation | Behavior |
|---|---|
| Engagement has zero status reports this quarter | Generate stub QBR + flag "QBR data sparse — recommend more frequent status reports" |
| No prior QBR exists (first one) | Skip the "vs prior quarter" comparison sections gracefully |
| Engagement is in AT_RISK state | Add prominent risk-recovery section at top of deck |
| Renewal already declined | Refocus QBR on transition / closeout instead of expansion |

## What this skill does NOT do

- Render to PowerPoint / Keynote (separate `deck-builder` skill consumes this markdown to produce slides)
- Send the deck (user reviews, sends via Gmail draft)
- Schedule the QBR meeting (`meeting-prep` skill if needed)
