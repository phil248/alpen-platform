---
name: manager-dd
description: Due diligence on a fund manager or general partner before commitment. Produces an IC (investment committee) memo from public sources + private docs. Use before any new fund commitment, when reviewing a GP for re-up, or evaluating a manager warm intro. Composes with alpen-deep-research orchestrator.
---

# manager-dd

## Status: stub (v0.1)

## Intent

Compress 20-40 hours of manager research into a structured IC memo. Composes with the `client-content-inventory` orchestrator from `alpen-deep-research` to deep-research the GP, then synthesizes into a decision-ready memo.

## Inputs

- Manager name + fund name + (optional) prior LP agreements
- Optional: tear sheet PDF, performance reports
- RAG kind `hfo-investment` (prior memos, prior GP interactions)

## Outputs

- `${VAULT}/HFO/Investments/IC-Memos/<manager-slug>.md` — IC memo
- Indexed into RAG kind `hfo-investment` for future reference

## Workflow (planned)

1. Dispatch `client-content-inventory --subject <manager-name> --depth standard`
2. Wait for orchestrator completion (typically 30-60 min for a manager)
3. Pull entity-extracted output (Person, Project=Fund, Publication, etc.)
4. Compose IC memo using template at `templates/default/ic-memo.md`
5. Write to vault + index to RAG

## IC memo structure (v0.1 template)

```
## Manager
## Fund
## Strategy & thesis
## Track record (prior funds)
## Team
## Terms (fees, GP commit, hurdle, carry)
## References (calls done, LPs spoken to)
## Risks
## Recommendation
## Decision (committed / pass / hold)
```

## v0.1 limitation

No automated scoring or comp-set assembly. Memo is decision-support, not decision-replacement.
