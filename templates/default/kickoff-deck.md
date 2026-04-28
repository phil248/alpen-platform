<!--
TEMPLATE: kickoff-deck
USE: produced by meeting-prep / kickoff-deck-builder skills at engagement start
APPLIES: every Tier 2 and Tier 3 engagement on its first day of work
FORMAT: markdown outline; rendered to slides via deck-builder
VOICE: confident; entity brand voice
-->

# Kickoff — {{deal.engagement_name}}

## Slide 1: Cover

- {{deal.client_name}} × {{entity.display_name}}
- {{deal.engagement_name}}
- Kickoff — {{today}}
- {{tenant.principal_name}}, {{tenant.principal_title}}

## Slide 2: Why we are here

{{deal.kickoff_purpose}}

## Slide 3: What we are doing together

- The engagement: {{deal.engagement_one_liner}}
- The outcome you will have: {{deal.target_outcome}}
- How we will know it worked: {{deal.success_metric}}

## Slide 4: How this works

```
Week 1                Weeks 2-{{deal.build_end_week}}              Final week
─────────             ──────────────────────              ──────────
Discovery       →     Build (with weekly demos)    →     Validation + handoff
```

## Slide 5: Schedule and milestones

| Milestone | Date | What it means |
|---|---|---|
| Discovery complete | {{deal.discovery_end}} | We have the future-state design locked |
| Mid-sprint demo | {{deal.midpoint_demo}} | First working version in front of you |
| Final delivery | {{deal.final_delivery}} | All deliverables ready for acceptance |
| Engagement end | {{deal.sow_end_date}} | Handoff complete; 30-day support begins |

## Slide 6: Working rhythm

- Weekly standup: {{deal.standup_day}} at {{deal.standup_time}} ({{deal.standup_duration}})
- Bi-weekly steering: {{deal.steering_cadence}}
- Status report: every {{deal.status_report_day}} by EOD
- Slack / email channel: {{deal.async_channel}}

## Slide 7: Team

### From {{entity.display_name}}

| Person | Role | When they show up |
|---|---|---|
| {{tenant.principal_name}} | {{deal.principal_role}} | {{deal.principal_when}} |
| {{tenant.partner_name}} | {{deal.partner_role}} | {{deal.partner_when}} |
| {{deal.contributor_3_name}} | {{deal.contributor_3_role}} | {{deal.contributor_3_when}} |

### From {{deal.client_name}}

| Person | Role |
|---|---|
| {{deal.client_sponsor_name}} | Executive sponsor |
| {{deal.client_poc_name}} | Day-to-day point of contact |
| {{deal.client_team_lead}} | Working team lead |

## Slide 8: What we need from you (this week)

- Access to {{deal.access_systems}} (target: {{deal.access_target}})
- {{deal.stakeholder_interview_count}} interview slots in the next 5 business days
- Confirmation of the working team
- Decision-authority delegation for {{deal.client_decision_areas}}

## Slide 9: Communication and escalation

- Routine questions: {{deal.async_channel}}, {{tenant.principal_name}} replies within 1 business day
- Same-week decisions: weekly standup
- Urgent (today): direct call to {{tenant.principal_name}} at {{tenant.principal_phone}}
- Escalation: {{tenant.principal_name}} → {{tenant.partner_name}} → {{tenant.escalation_executive}}

## Slide 10: Risks we will manage actively

| Risk | Why it matters | What we will do |
|---|---|---|
| {{deal.risk_1}} | {{deal.risk_1_impact}} | {{deal.risk_1_mitigation}} |
| {{deal.risk_2}} | {{deal.risk_2_impact}} | {{deal.risk_2_mitigation}} |

## Slide 11: What "done" looks like

- Deliverable 1: {{deal.deliverable_1}} ({{deal.deliverable_1_criteria}})
- Deliverable 2: {{deal.deliverable_2}} ({{deal.deliverable_2_criteria}})
- Deliverable 3: {{deal.deliverable_3}} ({{deal.deliverable_3_criteria}})
- Acceptance: 10 business days per deliverable per the SOW

## Slide 12: Questions and discussion

- What did we miss?
- What concerns do you want on the table now rather than later?
- What does success look like to you, in your words?

## Slide 13: Thank you

- {{tenant.principal_name}} — {{tenant.principal_email}}
- {{tenant.partner_name}} — {{tenant.partner_email}}
- Project channel: {{deal.async_channel}}
