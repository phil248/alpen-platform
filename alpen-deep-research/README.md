# alpen-deep-research

Open-web deep research with structured-entity extraction. Cross-cutting Alpen Platform capability — invoked by multiple departments to produce a persistent, queryable corpus on any subject (organization, person, fund, competitor, prospect).

## When to use

| Department | Use case |
|---|---|
| Revenue / Sales | Lead-org background research before discovery calls |
| Legal | Counter-party due diligence on contracts |
| Investments | Fund manager / GP background research |
| Knowledge / Research | Client deep-research engagements (e.g., CCG brain-health corpus expansion) |
| CompIntel | Deep competitor profiles |

## What it produces

- **Static deliverable** — markdown report at `~/Library/Application Support/Client-Inventories/<slug>/snapshot.md`
- **RAG-queryable index** — entities + content chunks ingested into the platform's RAG store, addressable by `subject` filter
- **Run log** — observability ledger at `~/Library/Application Support/Client-Inventories/<slug>/_state/run.jsonl`

## Architecture

```
client-content-inventory  (orchestrator, sonnet)
  ├─ memory-orchestration  (state, dedup, persistence)
  ├─ content-research      (discovery: PubMed, OpenAlex, ORCID, NIH RePORTER, Scholar, Listen Notes, news, web)
  ├─ content-acquisition   (tiered fetch: HTTP → Playwright → Chrome)
  ├─ content-processing    (transcription, OCR, doc extraction)
  └─ content-analysis      (entity extraction, dedup, classification)
```

The orchestrator dispatches subagents, never accumulates raw content in its own context, persists state between batches for crash-resume, and limits to 3 parallel subagents to respect rate limits.

## Entity model (12 types)

`Person`, `Organization`, `Project`, `Publication`, `Citation`, `SpeakingEngagement`, `Award`, `Event`, `Patent`, `IP`, `ContentAsset` (+1 reserved).

Each entity carries `subject_slug` (the inventory client) and `attributed_to` (Person | Organization).

## Usage

```
> Run a deep-research inventory on <organization name> — focus on <people | publications | speaking | full footprint>
```

The orchestrator picks up from there. For long-running batches you can resume after a crash via:

```
> Resume the deep-research inventory on <slug>
```

## State paths

- `~/Library/Application Support/Client-Inventories/<slug>/` — per-client state
- `~/Library/Application Support/Client-Inventories/<slug>/_state/` — orchestrator state (resume-from)
- `~/Library/Application Support/Client-Inventories/<slug>/_state/run.jsonl` — observability log

The slug is always lowercase. State is local-machine; portable to remote storage in v0.2.

## Provenance

Derived from the CBH (Center for BrainHealth) content-inventory work — Sandra Chapman corpus produced 297 entities, 150 deduplicated publications, 11MB / 1842 RAG chunks across 9 stages (March-April 2026). Hardened over Phase 0.5-0.7 with telemetry, stage-transition tracking, heartbeats, and per-source extraction. See `Alpen-platform-v0.1-architecture.md` memory for placement in the moat list.

## Status

v0.1 — same SKILLs and agents that ran the CBH inventory, repackaged as a portable plugin (no `~/Winnie/`-absolute paths). Eval workspace not included (tenant-specific).
