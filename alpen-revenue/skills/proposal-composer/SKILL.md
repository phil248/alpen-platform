---
name: proposal-composer
description: Render a Tier 1, 2, or 3 proposal from a scoped opportunity. Consumes templates/default/proposal-tier-N.md plus entity brand voice plus deal data from the scope-builder output (or a leads.db row at SCOPED stage). Writes ${VAULT}/Sales/Proposals/<lead-slug>.md, transitions the lead from SCOPED to PROPOSED in leads.db, runs voice-sweep on the output. Use when the user says "draft a proposal for X" or "compose the tier-2 proposal for the acme deal" or after scope-builder hands you a scoped deal.
---

# proposal-composer

## When to invoke

- After `scope-builder` finishes (it hands off automatically)
- When the user says "draft proposal for <client>" / "compose tier-N proposal for <deal>"
- When a deal in `leads.db` reaches stage `SCOPED` and `next_action` includes "proposal" / "compose proposal"

## Inputs

The skill expects ONE of:

1. **Scope handoff** — a structured object from `scope-builder` with all required `{{deal.*}}` fields populated
2. **Lead reference** — a slug pointing at a `leads.db` row (the skill loads frontmatter + history)
3. **Manual** — user provides client name + tier; skill fills via `templates/default/scope-questionnaire.yaml` (delegating to `scope-builder`)

## Workflow

### Phase 1: load + validate inputs

1. Determine `tier` from inputs (1, 2, or 3).
2. Load the right template: `templates/default/proposal-tier-{tier}.md`.
   Apply override resolution: check `templates/<entity-id>/proposal-tier-{tier}.md` first, then tenant override, then default.
3. Load tenant config (`tenants/<tenant-id>/config.yaml`) to populate `{{tenant.*}}`.
4. Load entity record (from config) to populate `{{entity.*}}`.
5. Load principal record to populate `{{principal.*}}`.
6. Compute runtime variables (`{{today}}`, `{{quarter}}`, `{{year}}`).

### Phase 2: detect missing variables

Before rendering, scan the template for `{{namespace.field}}` patterns. For each one:
- If resolvable from the loaded data, mark resolved.
- If missing and the field appears in `templates/default/scope-questionnaire.yaml`, queue an AskUserQuestion.
- If missing and NOT in the questionnaire, leave as-is and add to "needs your input" section.

Do NOT proceed to rendering with > 5 unanswered required questions; pause and ask in batch.

### Phase 3: render

Use Jinja2-style substitution. For each `{{namespace.field}}`:
- Replace with the resolved value
- HTML-escape only if the output target is HTML (default: markdown, no escaping)
- For numeric values like `{{deal.value}}`, format as "$X,XXX" using locale rules

### Phase 4: write output

Path: `${VAULT}/Sales/Proposals/<lead-slug>-tier-<N>.md`

If the file already exists:
- If unchanged content: skip + report "no changes"
- If changed: rename the prior version to `<lead-slug>-tier-<N>-v<N>.md` and write new

### Phase 5: voice-sweep

If the entity has `brand.no_em_dash: true` (most CCG content):

```bash
~/Winnie/bin/voice-sweep.sh "${VAULT}/Sales/Proposals/<lead-slug>-tier-<N>.md"
```

The sweep replaces em-dashes (—) and en-dashes (–) with hyphens, removes any other forbidden patterns from the entity's brand-voice rules, and exits non-zero if it can't make the file pass the voice checklist.

If voice-sweep fails: surface the failure to the user, do NOT continue.

### Phase 6: state transition

If the lead exists in `leads.db` at stage `SCOPED`:
- Update lead row: `stage = 'PROPOSED'`, `stage_entered_date = today`, `value_estimate = deal.value`
- Append to `lead_history`: `event_type='stage_change', from_stage='SCOPED', to_stage='PROPOSED', description='Proposal v<N> composed'`

If the lead doesn't exist (manual one-off proposal): write to `${VAULT}/Sales/Leads/<slug>.md` with frontmatter sufficient to seed leads.db on next regenerator run.

### Phase 7: report

Tell the user:
- Path to the proposal
- Tier and total value
- Any unresolved `{{...}}` variables left as placeholders
- Voice-sweep result
- State machine transition done (if applicable)

## Telemetry

Emit a `skill_completed` event after primary work using:

```bash
~/Winnie/bin/hfo-log \
  --skill proposal-composer \
  --event skill_completed \
  --outcome success \
  --tier <1|2|3> \
  --entity-id <ccg|alpen-tech> \
  --lead-slug <slug> \
  --variables-resolved <count> \
  --variables-unresolved <count> \
  --voice-sweep <pass|fail|skipped>
```

If the skill failed (couldn't complete its primary task), emit with `--outcome failure --error <short-string>` instead.

## Edge cases

| Situation | Behavior |
|---|---|
| Tier mismatch (e.g., Tier 1 deal but value > $30K) | Pause and ask user to confirm tier |
| Entity has no brand-voice file | Use `templates/default/brand-voice.md` |
| Multiple leads with similar names | Disambiguate by asking; never auto-pick |
| Scope questionnaire missing 5+ required fields | Stop; recommend running `scope-builder` first |
| Vault path not writable | Hard fail with clear error; do NOT silently downgrade target |

## Examples

### "Compose tier-2 proposal for the Eli Lilly deal"

1. Lookup `eli-lilly-brain-health-support` in leads.db
2. Notice tier not set → ask user to confirm Tier 2
3. Notice `deal.problem_statement` missing → ask user (one question, in-flow)
4. Render `templates/default/proposal-tier-2.md` (no CCG override exists yet)
5. Write `${VAULT}/Sales/Proposals/eli-lilly-brain-health-support-tier-2.md`
6. Voice-sweep (CCG entity): pass
7. Transition lead SCOPED → PROPOSED in leads.db
8. Report: "Tier 2 proposal composed at <path>; 1 unresolved variable left as `{{deal.success_metric}}` for your edit"

## What this skill does NOT do

- Send the proposal (the user opens, reviews, sends manually OR via Gmail draft from email-triage)
- Generate PDFs (deferred to v0.2)
- Negotiate (that's a different skill)
- Generate the underlying SOW (`sow-composer` skill is the next logical step after acceptance)
