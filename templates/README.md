# Templates

Default Alpen Platform templates + per-entity overrides.

## Resolution order (per tenant config schema)

```
templates.override_resolution: entity > tenant > default
```

For any template lookup (e.g., `proposal-tier-2.md`):

1. Look in `templates/<entity-id>/` — entity override (highest priority)
2. Look in `templates/<tenant-id>/` — tenant override
3. Fall back to `templates/default/` — platform default

## Template variables

Templates use `{{namespace.field}}` Jinja2-style variables (rendered by
the proposal-composer / scope-builder / qbr-prep skills, not by alpen-customize).
This is distinct from the `~~placeholder` substitution mechanism used by
alpen-customization (which targets plugin-internal text).

Common variables:
- `{{tenant.principal_name}}`, `{{tenant.partner_name}}`
- `{{entity.id}}`, `{{entity.display_name}}`, `{{entity.tagline}}`
- `{{deal.client}}`, `{{deal.tier}}`, `{{deal.value}}`, `{{deal.start_date}}`
- `{{principal.email}}`, `{{principal.signature_block}}`
- `{{today}}`, `{{quarter}}`, `{{year}}`

## Voice rules

Every template includes a `<!-- VOICE -->` comment block declaring which
voice rules apply. The composer skill consults the entity's brand_voice
config to pick the right ruleset (e.g., CCG: no em-dash, Krystal-frame).

## Tier ladder reference

| Tier | Alpen Tech | CCG |
|---|---|---|
| 1 | Platform + Configuration ($5-15K setup + $1-3K/mo) | Research Readout ($5-15K) |
| 2 | Customization + Process Redesign ($30-80K per sprint) | Program Design ($30-100K) |
| 3 | OCM-led Transformation ($150-300K all-in) | Enterprise Engagement ($150-500K annual retainer) |

## Provenance

Templates are Alpen IP — the second item on the moat list (per
Alpen-platform-v0.1-architecture.md). They are what makes a customized
fork of `anthropics/knowledge-work-plugins` into a sellable Tier 1
product. Default templates ship with the platform; tenants pay (Tier 2)
to customize them; Tier 3 includes new ones built for the engagement.
