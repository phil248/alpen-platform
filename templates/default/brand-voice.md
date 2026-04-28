<!--
TEMPLATE: brand-voice
USE: default brand voice rules; entity-specific overrides at templates/<entity>/brand-voice.md
APPLIES: every content-generating skill consults this before producing prose
FORMAT: rules + examples + post-write checklist
-->

# Brand voice — default

This file describes the default brand voice rules for an Alpen Platform tenant. Entity-specific overrides (e.g., CCG's Krystal-frame) live at `templates/<entity-id>/brand-voice.md` and take precedence.

## Universal rules (apply to every entity)

1. **Plain hyphens only.** Never em-dashes (—) or en-dashes (–). Hyphens are reserved for genuine compound words ("evidence-based", "science-to-practice"). Restructure the sentence rather than insert an em-dash.
2. **Active voice when possible.** Passive is acceptable when the actor is genuinely irrelevant.
3. **Sentence-case headings.** Title case is reserved for proper nouns and brand names.
4. **Numbers as digits at 10+; spelled at 1-9.** Exception: at the start of a sentence.
5. **Oxford comma.**
6. **No emoji** in formal content (proposals, MSAs, SOWs, QBRs). Emoji acceptable in informal Slack/Telegram messages and in skill conversational output where the user has opted in.

## Tone guidelines

- **Direct over diplomatic.** "This will not work" beats "This may present some challenges."
- **Specific over abstract.** "227 active leads" beats "a robust pipeline."
- **Curious over certain.** "We do not yet know X" is a strength, not a weakness, in client-facing analysis.
- **Brief over thorough.** Short response > long response for everything except formal deliverables.

## Common rejections

| Avoid | Use instead |
|---|---|
| "Best-of-breed" | name the specific thing you mean |
| "Holistic" | "across X, Y, and Z" |
| "Synergies" | "shared capabilities" or skip |
| "Drives value" | "produces $X in Y" |
| "Stakeholders" | "the people listed in section 3" |
| "Going forward" | "from now on" or skip |
| "Touch base" | "talk", "meet", "decide" |

## Signature reframe (per-entity override likely)

The default reframe pattern is "Not X — it's Y" but this varies by entity. Check `templates/<entity-id>/brand-voice.md` for entity-specific reframes and signature structures.

## First-use definitions

If your entity uses specialized terminology, list it here for first-use definitions. Default list is empty; tenants populate this in their override.

## Audience and register

Default register is "warmly direct executive" — confident enough to challenge a client, warm enough that the client wants the call. Adjust for entity context (e.g., CCG's academic register skews more formal; Alpen Tech skews more direct-operator).

## Post-write checklist

Run this checklist before declaring content complete. Failing any item triggers a rewrite, not a partial fix.

- [ ] Zero em-dashes or en-dashes (`grep -E '—|–' file.md` returns nothing)
- [ ] Reframe present in the major piece (per entity rules)
- [ ] First-use definitions present for any specialized terms
- [ ] No items from the "common rejections" table
- [ ] Specific numbers and named things rather than abstractions
- [ ] Headings in sentence case
- [ ] If formal deliverable: zero emoji
- [ ] If client-facing: brand assets used per `templates/<entity-id>/visual-identity.md`

## Enforcement

Each entity's customized SKILL templates should append a `## Voice` section that runs the post-write checklist. For platform-level enforcement, see the post-generation `perl -i -pe 's/—/-/g; s/–/-/g'` sweep used by `~/Winnie/agents/scheduled-ccg-briefing.md` (verified working).
