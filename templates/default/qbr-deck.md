<!--
TEMPLATE: qbr-deck (Quarterly Business Review)
USE: produced by qbr-prep skill (Customer Success dept) per active client
APPLIES: tier 1 quarterly; tier 2 mid-engagement and final; tier 3 per phase
FORMAT: this is a markdown outline; the qbr-prep skill renders it to slides via the
        deck-builder pipeline (uses the alpen-deck-builder skill, not Anthropic plugin's)
VOICE: data-driven; outcomes-focused; entity brand voice for headers
-->

# QBR — {{deal.client_name}} — {{quarter}}

## Slide 1: Cover

- {{deal.client_name}}
- Quarterly Business Review — {{quarter}}
- Prepared by {{tenant.principal_name}}, {{entity.display_name}}
- {{today}}

## Slide 2: Where we are

- Engagement: {{deal.engagement_summary}}
- Tier: {{deal.tier_name}}
- Quarter dates: {{quarter_start}} to {{quarter_end}}
- Engagement health: {{deal.health_score}}/100

## Slide 3: Last quarter — what we set out to do

- {{quarter.objective_1}}
- {{quarter.objective_2}}
- {{quarter.objective_3}}

## Slide 4: Last quarter — what actually happened

| Objective | Status | Outcome |
|---|---|---|
| {{quarter.objective_1}} | {{quarter.objective_1_status}} | {{quarter.objective_1_outcome}} |
| {{quarter.objective_2}} | {{quarter.objective_2_status}} | {{quarter.objective_2_outcome}} |
| {{quarter.objective_3}} | {{quarter.objective_3_status}} | {{quarter.objective_3_outcome}} |

## Slide 5: Metrics

| Metric | Last quarter | This quarter | Change |
|---|---|---|---|
| {{quarter.metric_1_name}} | {{quarter.metric_1_prev}} | {{quarter.metric_1_curr}} | {{quarter.metric_1_change}} |
| {{quarter.metric_2_name}} | {{quarter.metric_2_prev}} | {{quarter.metric_2_curr}} | {{quarter.metric_2_change}} |
| {{quarter.metric_3_name}} | {{quarter.metric_3_prev}} | {{quarter.metric_3_curr}} | {{quarter.metric_3_change}} |

## Slide 6: What worked

- {{quarter.worked_1}}
- {{quarter.worked_2}}
- {{quarter.worked_3}}

## Slide 7: What did not

- {{quarter.didnt_work_1}} — root cause: {{quarter.didnt_work_1_cause}}
- {{quarter.didnt_work_2}} — root cause: {{quarter.didnt_work_2_cause}}

## Slide 8: Voice of customer signals (last quarter)

Pulled from `voc-signals` RAG kind across this quarter's transcripts and meetings:

- Expansion signals: {{quarter.voc_expansion_count}}
- Objections raised: {{quarter.voc_objection_count}}
- Churn risk indicators: {{quarter.voc_churn_count}}

Top themes:

1. {{quarter.voc_theme_1}}
2. {{quarter.voc_theme_2}}
3. {{quarter.voc_theme_3}}

## Slide 9: Recommendations for next quarter

| Priority | Action | Owner | Why |
|---|---|---|---|
| 1 | {{next_quarter.action_1}} | {{next_quarter.action_1_owner}} | {{next_quarter.action_1_why}} |
| 2 | {{next_quarter.action_2}} | {{next_quarter.action_2_owner}} | {{next_quarter.action_2_why}} |
| 3 | {{next_quarter.action_3}} | {{next_quarter.action_3_owner}} | {{next_quarter.action_3_why}} |

## Slide 10: Next quarter — what we will do

- {{next_quarter.objective_1}}
- {{next_quarter.objective_2}}
- {{next_quarter.objective_3}}

## Slide 11: Investment — current period

| Component | Spent | Remaining | Notes |
|---|---|---|---|
| {{deal.tier_name}} fees | ${{quarter.fees_spent}} | ${{quarter.fees_remaining}} | {{quarter.fees_notes}} |
| Travel and OOP | ${{quarter.travel_spent}} | n/a | {{quarter.travel_notes}} |

## Slide 12: Renewal / expansion conversation

- Renewal date: {{deal.renewal_date}}
- Renewal recommendation: {{deal.renewal_recommendation}}
- Expansion opportunities (from VoC + observation):
  - {{deal.expansion_1}}
  - {{deal.expansion_2}}

## Slide 13: Asks of you

| Ask | Why | Decision needed by |
|---|---|---|
| {{deal.ask_1}} | {{deal.ask_1_why}} | {{deal.ask_1_due}} |
| {{deal.ask_2}} | {{deal.ask_2_why}} | {{deal.ask_2_due}} |

## Slide 14: Thank you / Q&A

- {{tenant.principal_name}} — {{tenant.principal_email}}
- {{tenant.partner_name}} — {{tenant.partner_email}}
