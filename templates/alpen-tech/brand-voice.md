<!--
TEMPLATE: brand-voice (Alpen Tech entity override)
APPLIES: every content-generating skill operating under entity=alpen-tech or entity=alpen
PRECEDENCE: this file takes priority over templates/default/brand-voice.md
-->

# Brand voice — Alpen Tech

Read this file before any Alpen Tech content. It overrides the default brand voice rules.

## Tagline

> "Business change moves P&L. AI earns its keep."

This is the elevator-pitch reframe. Use it (or a clear variant) in any major piece of Alpen Tech content. The structure: "X moves the result. Y earns its place."

## The Krystal-frame (lead public narrative)

Per the 2026-04-25 strategic alignment, Phil's primary public narrative for Alpen Tech is delivered through Krystal-as-named-subject content. The frame:

> "Krystal started CCG solo. Phil built HFO/Winnie to give her enterprise-grade infrastructure. CCG produced $884K Year 1 net. Now we're productizing the platform for other solo founders and SMBs."

CCG is the canonical demo environment, named publicly.

### Cadence rules

- **Krystal:** 3 posts/week on existing themes; 1-in-4 AI-ops-flavored. Two signature posts in first quarter.
- **Phil:** 2-3 posts/week, ~30% Krystal-as-named-subject content with cross-link.
- **LinkedIn naming rule:** do NOT anchor Phil's personal content around Alpen Tech directly. Reference work and platform via Krystal-frame; convert via bio link to alpentech.ai.

## Voice attributes

**We Are:**
- Declarative — clear assertions, not hedged
- P&L-focused — every capability tied to a business metric
- Operator-fluent — speaks the language of CTOs and Heads of Engineering, not the language of consultants
- Concrete — names systems, vendors, costs, hours; avoids abstractions
- Short — 2-paragraph posts beat 5-paragraph posts

**We Are Not:**
- Generic AI hype ("revolutionize", "transform", "unlock", "leverage")
- Vendor-shilling (Anthropic is a substrate, not a sales pitch)
- Founder cult-of-personality (the work speaks; Phil is a builder, not an influencer)
- Abstraction-laden ("synergy", "alignment", "ecosystem")

## Positioning

Alpen Tech operates as a productized AI ops platform with three tiers (per Alpen-Tech-strategic-alignment-2026-04-25). The lead with prospects is the Tier 1 platform; Tier 2 and 3 are escalation paths revealed when the prospect's needs justify them. Don't lead with Tier 3 transformation work to a Tier 1 prospect.

## Forbidden language

In addition to the universal "common rejections" table:

- "Revolutionize", "transform" (use "change" or "redesign" with specifics)
- "Unlock value" (specify what value, in what unit)
- "Leverage" (use "use")
- "Empower" (use "lets you" or "gives you")
- "Game-changer" (skip)
- "Synergy" (skip)
- "Ecosystem" (skip unless naming a specific marketplace)
- "Platform" (acceptable but specify which platform you mean — Alpen Platform vs. customer's platform)
- "AI-powered" (assumed; redundant)

## Required structures

### Three-line opener for posts

Most Alpen Tech posts open with a three-line structure:

```
[Specific observed thing or counterintuitive claim]
[Why most people get it wrong]
[The reframe / what we did instead]
```

Example:

> "We turned off our project tracker for two weeks.
> Most teams add tools when they're stuck; we removed one.
> Engagement went up. The tool was the friction."

### The tier-ladder reframe (proposals only)

Every Alpen Tech proposal explicitly addresses why a given tier is the right tier — and why adjacent tiers aren't. This is in the proposal template (`proposal-tier-N.md`) but the brand-voice nuance is: be concrete about the disqualifier ("you have a 50-person team and need ROI in Q3 — Tier 3 transformation timeline doesn't fit").

## Visual identity

- Tagline rendering: small caps, weight 600, NOT all-caps
- Colors: TBD — derive from current alpentech.ai
- Logo: TBD
- Default photography: TBD (avoid stock; prefer architectural / mountain / clean-tech aesthetics consistent with "alpen")

## Post-write checklist (Alpen Tech-specific)

In addition to the default checklist:

- [ ] No "revolutionize / transform / unlock / leverage / empower / game-changer / synergy / ecosystem" in formal content
- [ ] Tagline (or variant) present in major pieces
- [ ] Three-line opener used for posts
- [ ] Specific names, numbers, vendors, costs — not abstractions
- [ ] Phil's personal content cross-referenced to alpentech.ai via bio link, not direct mention
- [ ] If Krystal-as-subject: explicit consent / collaboration confirmed
- [ ] Em/en dash sweep: `grep -E '—|–' file.md` returns nothing
