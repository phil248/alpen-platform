---
name: scope-builder
description: Walk through templates/default/scope-questionnaire.yaml with a discovery-call transcript or directly with the user. Produces a structured scope object that proposal-composer consumes. Transitions the lead from DISCOVERED to SCOPED in leads.db. Use when the user says "scope the X deal", "build a scope for X", or after a discovery call with a prospect.
---

# scope-builder

## When to invoke

- After a discovery call (Plaud transcript landed in vault, opportunity-review picked up the deal, next-action says "scope")
- When the user says "scope the <client> deal" or "let's build the scope for X"
- When a deal in `leads.db` reaches stage `DISCOVERED` and `next_action` says "scope" or similar

## Inputs

ONE of:
1. **Transcript reference** — path to a Plaud transcript in vault (the skill extracts what it can, asks the rest)
2. **Lead reference** — slug pointing at `leads.db` row at stage DISCOVERED
3. **Manual** — user provides client name + entity; skill walks the questionnaire fully

## Workflow

### Phase 1: load questionnaire + context

1. Load `templates/default/scope-questionnaire.yaml`.
2. If transcript provided: extract candidate values for fields by section.
3. Load `leads.db` row if lead reference provided.

### Phase 2: walk sections

For each section in the questionnaire:
1. For each `required: true` field NOT yet filled:
   - If transcript or prior data has a candidate, propose it: "Looks like X — confirm?"
   - Otherwise: AskUserQuestion (one at a time; group by section to reduce context-switching)
2. For `required: false` fields: skip unless user proactively offered

Apply `when:` conditions strictly. If `when: "deal.tier in [2, 3]"` and tier is 1, skip those sections.

### Phase 3: validate scope coherence

Before handing off:
- Check tier value matches range: Tier 1 ($1K-$15K monthly), Tier 2 ($30K-$80K), Tier 3 ($150K-$300K+). Flag mismatches with a "confirm tier?" question.
- Check engagement timing fits tier: Tier 1 = 4 weeks setup; Tier 2 = 4-8 week sprint; Tier 3 = 12-24 weeks.
- Check named team allocation makes sense: Tier 1 doesn't need both principals; Tier 3 typically does.

### Phase 4: persist scope

Write the scope object to `${VAULT}/Solutions/Scopes/<lead-slug>.md` with:
- Frontmatter: lead_slug, tier, value, created_at, scoper (skill name)
- Body: rendered scope as a human-readable doc
- Append to History section if file already exists (don't overwrite)

### Phase 5: state transition

If the lead exists in `leads.db` at stage DISCOVERED:
- Update lead row: `stage = 'SCOPED'`, `stage_entered_date = today`, `tier = <tier>`, `value_estimate = deal.value`
- Append to `lead_history`: `event_type='stage_change', from_stage='DISCOVERED', to_stage='SCOPED', description='Scope built (Tier <N>, $<value>)'`

### Phase 6: hand off to proposal-composer

Default behavior: invoke `proposal-composer` automatically with the scope object.
If the user said "just scope it, don't propose yet": stop and report.

## Telemetry

```bash
~/Winnie/bin/hfo-log \
  --skill scope-builder \
  --event skill_completed \
  --outcome success \
  --tier <1|2|3> \
  --entity-id <ccg|alpen-tech> \
  --lead-slug <slug> \
  --questions-asked <n> \
  --transcript-extracted-fields <n>
```

## Edge cases

| Situation | Behavior |
|---|---|
| Lead doesn't exist in leads.db | Create stub at ${VAULT}/Sales/Leads/<slug>.md; populate later |
| Tier mismatch with value | Pause; "the value you gave is $X but Tier <N> range is $Y-$Z; confirm?" |
| Discovery transcript has < 5 questionnaire-relevant utterances | Continue but warn user that most questions will need manual answers |
| Discovery transcript references competitive evaluation | Add `deal.alternatives_considered` automatically |

## What this skill does NOT do

- Make the tier decision unilaterally — always confirm with user
- Render the proposal (that's `proposal-composer`)
- Generate the SOW (after proposal acceptance)
- Negotiate price (that's a future negotiation skill)
