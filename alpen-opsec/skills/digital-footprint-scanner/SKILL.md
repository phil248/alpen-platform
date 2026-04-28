---
name: digital-footprint-scanner
description: What does the open web know about the principal? Composes with alpen-deep-research/client-content-inventory --subject <principal-name>. Surfaces public info that could be used for social engineering, spear-phishing, or doxxing. Use annually or before high-profile events.
---

# digital-footprint-scanner

## Status: stub (v0.1)

## Intent

Same machinery used to research clients, turned inward. Run a deep-research inventory on the principal (and optionally family members) to surface what an adversary would find. Use the report to remove unnecessary exposure (data brokers, expired LinkedIn employments, abandoned blog accounts, etc.).

## Inputs

- Principal name + known aliases / handles / domains
- Optional: family members' names (with explicit principal consent)

## Outputs

- `${VAULT}/HFO/OPSEC/Footprint/YYYY-MM-footprint-<name>.md`
- Recommended deletion / suppression actions per item found
- (v0.2) Auto-routed to data-broker opt-out workflows (Spokeo, Whitepages, etc.)

## Composition

```
digital-footprint-scanner
  → client-content-inventory --subject <principal-name> --scope public-only
    → returns: 12-entity output (Person, Org employments, Publications, Speaking, etc.)
  → digital-footprint-scanner classifies each entity by exposure risk
  → produces footprint report
```

## v0.1 limitation

Detection only. No automated suppression / opt-out wiring yet (those flows are mostly manual or paid services).
