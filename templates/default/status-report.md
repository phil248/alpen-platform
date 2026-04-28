<!--
TEMPLATE: status-report
USE: weekly engagement status, produced by status-report-composer (Delivery dept)
APPLIES: every active engagement, every Friday PM (per scheduled-status-report cron)
FORMAT: short — one page printed; not a slide deck
VOICE: factual; entity brand voice
-->

# Status — {{deal.engagement_name}} — Week of {{week_start_date}}

**To:** {{deal.client_poc_name}}, {{deal.client_sponsor_name}}
**From:** {{tenant.principal_name}}, {{entity.display_name}}
**Date:** {{today}}
**Engagement health:** {{deal.health_score}}/100  ({{deal.health_color}})

---

## TL;DR

{{week.tldr}}

---

## Done this week

- {{week.done_1}}
- {{week.done_2}}
- {{week.done_3}}

## In flight

- {{week.in_flight_1}} — {{week.in_flight_1_status}}
- {{week.in_flight_2}} — {{week.in_flight_2_status}}

## Next week

- {{week.next_1}}
- {{week.next_2}}
- {{week.next_3}}

## Risks and blockers

| Item | Severity | Owner | Mitigation |
|---|---|---|---|
| {{week.risk_1}} | {{week.risk_1_sev}} | {{week.risk_1_owner}} | {{week.risk_1_mitigation}} |
| {{week.risk_2}} | {{week.risk_2_sev}} | {{week.risk_2_owner}} | {{week.risk_2_mitigation}} |

## Asks of you

- {{week.ask_1}} (need by: {{week.ask_1_due}})
- {{week.ask_2}} (need by: {{week.ask_2_due}})

## Schedule and milestones

- Last completed: {{milestone.last_completed}} ({{milestone.last_completed_date}})
- Next milestone: {{milestone.next}} ({{milestone.next_date}})
- Engagement end: {{deal.sow_end_date}} ({{deal.weeks_remaining}} weeks remaining)

## Hours and budget (Tier 2/3 only)

- Hours this week: {{week.hours_used}}
- Hours engagement-to-date: {{deal.hours_total}} of {{deal.hours_budget}} budgeted
- Fees billed engagement-to-date: ${{deal.billed_to_date}} of ${{deal.value}}
- On track? {{deal.budget_status}}

---

Questions, concerns, or course-corrections — reply or call.

— {{tenant.principal_name}}
