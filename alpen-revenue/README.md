# alpen-revenue

Revenue extensions for the Alpen Platform. Sits on top of the upstream Anthropic `sales` plugin and adds the consumer skills that actually render the templates pack into real deliverables.

## Skills

| Skill | Reads | Produces |
|---|---|---|
| `proposal-composer` | scope-questionnaire output, brand-voice, templates/default/proposal-tier-N.md | `${VAULT}/Sales/Proposals/<lead-slug>.md` (and PDF if `pdf_generation` enabled) |
| `scope-builder` | discovery-call transcript, templates/default/scope-questionnaire.yaml | filled scope object → handed to proposal-composer |
| `qbr-prep` | engagements.db (current quarter), VoC RAG signals, templates/default/qbr-deck.md | `${VAULT}/CS/QBRs/<engagement-id>-<quarter>.md` (rendered to slides separately) |
| `status-report-composer` | engagements.db (this week), templates/default/status-report.md | `${VAULT}/Delivery/Engagements/<id>/Status-Reports/YYYY-MM-DD.md` |

## How variables resolve

Templates use `{{namespace.field}}` Jinja2-style variables (NOT `~~` placeholders — those are for plugin-internal customization). The composer skills resolve them in this order:

```
1. {{deal.X}}      — from the scope-questionnaire / scoper output
2. {{tenant.X}}    — from tenants/<tenant-id>/config.yaml
3. {{entity.X}}    — from the entity selected for this deal (CCG / Alpen Tech)
4. {{principal.X}} — from the principal who owns this deal
5. {{today}}, {{quarter}}, {{year}} — runtime computed
```

Unresolved variables are left as-is and surfaced in a "needs your input" section at the bottom of the rendered output.

## State-machine integration

| Skill | Triggers state transition |
|---|---|
| `scope-builder` | `leads.db: lead.stage` DISCOVERED → SCOPED |
| `proposal-composer` | `leads.db: lead.stage` SCOPED → PROPOSED |
| `qbr-prep` | none directly; reads engagements.db only |
| `status-report-composer` | writes `engagement_status_report` row |

## Composition with upstream sales plugin

The upstream `sales` plugin handles the *prospecting / call-prep / outreach* end of the funnel (account-research, draft-outreach, daily-briefing, pipeline-review, etc.). This plugin handles the *closing / contracting / delivery* end. They share the same lead-id keyspace.

Workflow: upstream `sales/account-research` → upstream `sales/call-prep` → discovery call → THIS PLUGIN's `scope-builder` → THIS PLUGIN's `proposal-composer` → upstream `legal/contract-review` → contract execution → THIS PLUGIN's `status-report-composer` (weekly) → THIS PLUGIN's `qbr-prep` (quarterly).

## Voice enforcement

Every composer skill calls `~/Winnie/bin/voice-sweep.sh` after writing output, when the entity has `brand.no_em_dash=true`. See `feedback_alpen_storage_patterns.md` and the entity's brand-voice template for full rules.
