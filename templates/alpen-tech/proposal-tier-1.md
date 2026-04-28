<!--
TEMPLATE: proposal-tier-1 (Alpen Tech entity override)
TIER: 1 (Platform + Configuration)
USE: subscription-style; recurring monthly; defined onboarding window
PRICING: $5K-$15K setup + $1K-$3K/month
DURATION: 4-week onboarding, then ongoing
VOICE: Alpen Tech (templates/alpen-tech/brand-voice.md) — declarative, P&L-focused, no "revolutionize/transform/unlock/leverage"
PRECEDENCE: overrides templates/default/proposal-tier-1.md when entity=alpen-tech
-->

# Alpen Platform — {{deal.client_name}}

**Prepared for:** {{deal.client_name}}
**Prepared by:** {{tenant.principal_name}}
**Date:** {{today}}
**Validity:** 30 days

---

## Three-line summary

{{deal.three_line_opener}}

(Default if unfilled: "Your team is buying tools to make AI useful. Most teams add tools when they're stuck; we configure the tools you already have so they earn their place. The Alpen Platform installs in 4 weeks and pays for itself in saved hours, not deferred features.")

---

## What ships

A working Alpen Platform install in your environment, configured for your team's tools and workflows, with monthly operations support. Specifically:

- **Platform install** — the open-source Alpen Platform fork (`anthropics/knowledge-work-plugins` extended with our tier-ladder, brand-voice, and IP MCPs) running against your accounts
- **Connector wiring** — OAuth into the {{deal.connector_count}} systems you actually use; we don't connect things you don't
- **Customization** — your team's terminology, brand voice, and reporting cadence baked into the platform's templates
- **Kickoff workshop** — 90 minutes, up to 6 people from your team
- **Runbook** — your team's playbook for using, modifying, and extending the platform after we hand off
- **Monthly operations** — 4 hours of platform support per month for drift fixes, new connectors, skill tuning

## What does not ship

- A done-for-you service. Your team operates the platform; we configure and support.
- A custom build. The platform is pre-built; we configure.
- Unlimited consulting. Additional time billed at our standard rate.

---

## Schedule

| Week | What happens | What you have at end of week |
|---|---|---|
| 0 | Discovery — joint working session | Map of your tool stack + the 5-8 workflows we'll configure first |
| 1 | Install — platform + OAuth wired | Working baseline against your accounts |
| 2 | Configure — your terminology, brand voice, reporting | Tuned skills for the highest-value workflows |
| 3 | Test runs against real workflows with your team | Validated capability + adjustments |
| 4 | Kickoff workshop + runbook handoff | Your team running the platform; subscription begins |

---

## Investment

| Component | Amount | Cadence |
|---|---|---|
| Platform setup | ${{deal.setup_fee}} | One-time, due at signature |
| Monthly subscription | ${{deal.monthly_fee}}/mo | First of month |
| Annual prepay discount | 10% off subscription | Optional |

**Total first-year investment: ${{deal.year_one_total}}**

## What this earns

Tier 1 customers report measurable outcomes within 90 days:

| Metric | Typical month-3 result |
|---|---|
| Hours per week reclaimed by configured agents | 8-15 hours |
| Repeated tasks now automated | 15-25 |
| Direct cost savings (depending on stack) | $2K-$8K/mo |

We track these in the platform's observability dashboard. If the numbers don't appear, we re-tune for free until they do.

---

## Why us, not generic AI consulting

| | Generic AI consulting | Alpen Platform |
|---|---|---|
| Start state | A blank slate | A working platform you fork on day 1 |
| Time to first value | 8-12 weeks | 4 weeks |
| Customization model | Custom code per engagement | Config files + templates |
| What you own | A bespoke build | An open-source fork your team can extend |
| Renewal risk | High — "do we re-engage?" | Low — subscription continues, value compounds |

---

## What we need from you

- A primary point of contact, ~2 hours/week during weeks 0-4
- OAuth-admin access to {{deal.access_systems}} during install week
- 6 stakeholders for a 90-minute kickoff workshop in week 4
- A vault or shared drive where the platform writes deliverables (we recommend Obsidian or any markdown-friendly drive)

---

## Acceptance

This proposal is accepted upon signature below. Alpen Tech will issue a service order and onboarding schedule within 3 business days.

---

**{{deal.client_name}}**

Signature: __________________________________________

Name: ______________________________________________

Title: _______________________________________________

Date: _______________________________________________

---

**Alpen Tech**

Signature: __________________________________________

Name: {{tenant.signatory_name}}

Title: {{tenant.signatory_title}}

Date: _______________________________________________
