---
name: client-content-inventory
description: "Comprehensive client content inventory workflow. USE THIS SKILL whenever the user asks to inventory, catalog, map, snapshot, or audit a client organization's publications, speaking engagements, media presence, awards, research output, citations, or full digital footprint — even if they don't say the word 'inventory'. Trigger on requests to 'pull together everything X has published', 'map the research output of org Y', 'build a content snapshot for client Z', 'discover all the public content for an organization', or any combination of {client/org/nonprofit/advisor} with {publications/speaking/awards/media/content/digital footprint}. Coordinates 5 subagents (research, acquisition, processing, analysis, memory-orchestration) to produce a static deliverable plus a RAG-queryable index. Run for any new or recurring client-content audit engagement; do not pick a narrower skill when this orchestrator fits."
---

# client-content-inventory

## CRITICAL RULES (NON-NEGOTIABLE)

0. **Never accumulate raw subagent output in context; only summaries flow back to you.** The orchestrator's context is precious — every subagent must persist results to disk and return only a short summary (paths + counts + key findings). If you ever read raw scraped HTML, full PDF text, or full transcripts back into your own turn, you are doing it wrong.

1. **You orchestrate; subagents do the work.** Use the Agent tool to dispatch subagents. Never try to do content discovery, acquisition, processing, or analysis directly in your own context. Your job is the plan and the scoreboard.

2. **Persist-and-return-summary discipline.** Subagents return only counts, file paths, failure logs, and next-batch signals. If a subagent's response includes more than 1KB of raw content, that's a contract violation; stop and report.

3. **Verify subagent claims with disk inspection.** After each subagent dispatch, use Bash `ls -la` or `sqlite3 SELECT COUNT` to confirm the claimed work actually happened. If discrepancy: log it, re-dispatch with explicit instructions, escalate if persistent.

4. **Lowercase client_slug everywhere.** State paths use lowercase (`~/Library/Application Support/Client-Inventories/cbh/`). Do not normalize or change case across calls.

5. **Failure recovery via state.** If you crash or hit budget mid-run, on resumption call memory-orchestration op=get_state, identify next pending batch, dispatch from there. Do not redo completed work.

6. **Concurrency limit: 3 subagents in parallel max.** Never hit the same external API in parallel from two subagents.

7. **Return failure honestly.** If a stage fails, return `status: failed` with the failed stage and error. Do not fabricate completion of stages that hit issues.

8. **One file per entity. Never roll-ups, never lists.** (added 2026-05-07; audit findings #13 NEW). Each publication, media-mention, amplification, speaking-engagement, award-received, etc. MUST be persisted as its OWN JSON file under the kebab-case directory for its kind (e.g., `publications/<slug>.json`, `amplifications/<slug>.json`). Never write a single file containing a list of publications, never write a roll-up file with `publications: [...]` nested inside. Two CBH agents violated this on 2026-05-07 (Robertson wrote 10 expansion publications as one rollup-with-nested-list; Ling wrote them as a single bare-list file) — downstream analytics expects per-record files and silently mis-counts when given lists. memory-orchestration op=persist_batch must reject any batch where a single intended-record file contains a top-level list of records. If you receive a subagent summary suggesting list-style persistence, halt and re-dispatch.

9. **Dashboards MUST be computed from disk + SQLite, never from prior agent claims.** (added 2026-05-07; audit finding #2). Phase D dashboards on 2026-05-07 had every entity-type count wrong (publications 234 vs disk 236, media-mentions 23 vs 45, speaking-engagements 0 vs 16, "117.6% ORCID coverage" computed from synthesized counts). Do NOT generate the final dashboard via LLM narrative synthesis. Stage 10 dispatches `content-analysis op=build_verified_dashboard` which runs a deterministic Python script that reads `find . -name '*.json'` per entity-type folder and queries SQLite for canonical counts. Free-text dashboard counts from agent narratives are an antipattern.

## Purpose

Orchestrate the complete inventory pipeline for a client. Read parameters, dispatch subagents in sequence, persist state at every step, produce the snapshot deliverable.

You are the planner and the scoreboard. Subagents do the volume work and return condensed summaries; you maintain the run state and the next-step decisions.

## Inputs (passed when invoked)

```yaml
client:
  name: string                       # e.g., "CBH"
  full_name: string                  # e.g., "Center for BrainHealth"
  primary_url: url
  linkedin_url: url
  other_owned_urls: list[url]

scope:
  content_scope: A | B | C | D
  people_scope: A | B | C | D | E | F
  time_horizon: 5y | 10y | 25y | all | asymmetric
  free_sources_only: bool

seed_people: list[string]

paths:
  vault_root: path                   # Drive-mounted, exact case (e.g., "/.../My Drive/Client-Inventories/CBH")
  state_root: path                   # Local-only, lowercase (e.g., "~/Library/Application Support/Client-Inventories/cbh")
  rag_store_path: path               # Per-client

delivery:
  target: drive | sharepoint | export-only
  drive_path: path
  include_rag_demo: bool
  include_analytics: list[string]
  
phase: 1 | 2 | 3 | 4 | 5
run_stage: int | "all"
op: string | null

# Added 2026-05-07 (audit finding #14):
dependency_policy: hard-fail | soft-fail   # default: hard-fail for production runs
verify_from_disk: bool                     # default: true; Stage 10 dashboards always disk-verified
```

## Pipeline (Phase 1 sequence)

For each stage, dispatch the appropriate subagent via the Agent tool. Wait for response. Verify on disk. Persist progress before moving to next stage.

```
Stage 1: Initialize run state
  - Dispatch: Agent(subagent_type="memory-orchestration",
                   prompt="op=init client_slug=<slug> state_root=<path> vault_root=<path> run_id=<id> phase=<n>")
  - Verify: Bash ls -la '<state_root>/_state/inventory-state.json'
  - On failure: stop and report

Stage 2: Seed identification (owned-property sweep)
  - Dispatch: Agent(subagent_type="content-research",
                   prompt="target=seed_owned_property_sweep client_slug=<slug> ...")
  - Receive: discovered_records (people, projects, events, etc.)
  - Dispatch persist: Agent(subagent_type="memory-orchestration",
                            prompt="op=persist_batch batch=<records> batch_id=<id> subagent=content-research")
  - Verify: Bash sqlite3 SELECT COUNT(*) FROM entities GROUP BY entity_type

Stage 3: Per-person publication discovery
  - For each person in seed_people:
    - Loop: dispatch content-research with target=person_publications, batch_offset=N
    - Receive: discovered_records, next_batch_offset
    - Dispatch persist
    - If next_batch_offset is null, person done; move to next person
  - Verify: SQLite COUNT(*) WHERE entity_type='publication'

Stage 3.5: ORCID truth-check (NON-SKIPPABLE invariant; added 2026-05-07; audit finding #3)
  - For each person in seed_people with an `orcid_id`:
    - Bash: curl -s "https://pub.orcid.org/v3.0/<orcid>/works" -H "Accept: application/json"
            | jq '.group | length'
      Captures ORCID's authoritative count of distinct works.
    - SQLite: SELECT COUNT(*) FROM entities WHERE entity_type='publication'
              AND json_extract(blob, '$.authors') LIKE '%<person_slug>%'
    - Compute delta_pct = (orcid_count - inventory_count) / orcid_count
    - If delta_pct > 0.05 (inventory < ORCID by more than 5%):
        - Mark run.verifications.orcid_truth_check[<person>] = "FAIL: <inv>/<orcid>"
        - REFUSE to proceed past this stage unless caller passes
          paths.dependency_policy=soft-fail OR an explicit override flag.
        - When refused: emit hfo-log heartbeat with current_activity describing
          the gap, return status=partial with current_stage=3.5, do NOT advance.
    - If delta_pct <= 0.05: log "OK: <inv>/<orcid>" and advance.
  - This is the root cause of CBH Phase 1 missing 22 of Sandra's >250-cite papers
    (including her single most-cited at 676 citations). Failing loud here is the
    point — silent under-discovery is the bug being prevented.

Stage 4: Per-person non-publication discovery
  - For each person in seed_people:
    - Dispatch content-research with target=person_non_publication_content
    - Receive and persist
  - Verify counts

Stage 5: Org-level content discovery
  - Dispatch content-research with target=org_level_content
  - Receive and persist
  - Verify counts

Stage 6: Asset acquisition
  - Build URL list from discovered records (publications with PDFs, talks with videos, etc.)
  - Loop in batches of 50:
    - Dispatch content-acquisition with batch of URLs
    - Receive ContentAsset records
    - Dispatch persist
  - Verify: Bash ls -la '<vault_root>/_assets/' to confirm files

Stage 7: Asset processing
  - Loop in batches of 10:
    - Dispatch content-processing with batch of assets
    - Receive transcript records
    - Dispatch persist
  - Verify: ls '<vault_root>/_assets/transcripts/' has expected count

Stage 8: Entity resolution + analytics
  - Dispatch content-analysis with op=resolve_entities
  - Dispatch content-analysis with op=classify_themes
  - Dispatch content-analysis with op=compute_citation_graph
  - Dispatch content-analysis with op=compute_coauthor_network
  - Dispatch content-analysis with op=compute_distributions
  - Verify: ls '<vault_root>/_analytics/' has all expected CSV/JSON files

Stage 9: Finalize and trigger RAG ingest (NON-SKIPPABLE; audit finding #9)
  - This stage is non-skippable, even on resumed runs and on Phase 2/3/4 invocations.
    Each phase's writes must flow into RAG before the run can claim success.
  - Dispatch memory-orchestration with op=finalize_run
  - memory-orchestration triggers the RAG ingest (mcp__cbh_rag__rag_ingest equivalent
    or rag CLI) over all entities created/modified during this run.
  - Smoke test (REQUIRED): pick one entity slug created during this run, dispatch
    a sample mcp__cbh_rag__rag_search for its title or canonical phrase. If 0 hits,
    the ingest didn't take — fail the run with status=failed even though prior
    stages succeeded. Stale RAG = silently broken deliverable.
  - Verify: Bash ls -la '<rag_store_path>' shows substantial size after ingest.

Stage 10: Generate verified-from-disk dashboard (audit finding #2)
  - Dispatch content-analysis with op=build_verified_dashboard.
    That op runs a deterministic Python script (lib/build_dashboard.py) that:
      * counts entity JSONs by directory (`find <vault>/<kind>/ -name '*.json' | wc -l`)
      * counts chunks in RAG SQLite by source_kind
      * computes ORCID-vs-inventory delta per seed person (re-runs the Stage 3.5 check)
      * outputs `_deliverable/<date>-verified-dashboard.md` with disk-anchored counts
  - LLM-written dashboards are FORBIDDEN at this stage. The orchestrator's job here
    is dispatch + verification, not synthesis. If you find yourself drafting count
    prose, stop — the script is the source of truth.
  - Verify: file exists at `_deliverable/<date>-verified-dashboard.md` and counts
    match `find` output for each kind directory.
```

## Phase 1 MVP scope (CBH)

For MVP, restrict per-person work to Sandra Bond Chapman only. Run org-level discovery in full. Pipeline same; just limit `seed_people` to Sandra's variants.

## Persist-and-return-summary discipline

You never see raw subagent output. Every subagent call returns:
- Counts of items processed
- File paths to persisted outputs
- Brief failure log
- "Next batch ID" or "queue empty" signal
- `verifications` field with the actual ls/sqlite output proving the work happened

You make dispatch decisions on these summaries alone. If you find yourself reading individual record content from a subagent's output, that's a contract violation.

## Failure recovery

If you crash or hit budget mid-run:
1. Dispatch memory-orchestration op=get_state
2. Identify last successful batch_id and current_phase from state
3. Dispatch from the next pending batch; never redo completed work
4. Append a `resumed_at` event to run-log.jsonl

## Concurrency rules

- Up to 3 subagents in parallel where independent (e.g., content-acquisition fetching while content-research discovers next batch)
- Never hit same external API in parallel; sequence API-bound work (PubMed especially)
- Max-session-window discipline: avoid full-pipeline runs during 08:00-18:00 working hours

### Stage-specific concurrency budgets

Different stages have different parallelism opportunities. Earlier stages are sequential by nature; later stages benefit from fan-out.

- **Stage 2 (seed sweep):** sequential. Single content-research dispatch.
- **Stage 3 (per-person publications):** sequential per-person; within a person, ORCID bulk-fetch makes parallelism unnecessary.
- **Stage 4 (per-person non-pub):** can run concurrent with later iterations of Stage 3 if person-disjoint. For Phase 1 MVP (Sandra only), sequential.
- **Stage 5 (org-level):** can run concurrent with Stage 3 or Stage 4 if state-file write contention is acceptable (different entity types → different folders → safe; dedup-cache and inventory-state.json have minor read-modify-write race; for MVP, acceptable risk).
- **Stage 6 (asset acquisition):** highly parallel. Different hosts can fetch simultaneously, up to 5 concurrent downloads if hosts differ. Same host: sequential with rate-limit respect.
- **Stage 7 (asset processing):** sequential or limited parallel. Whisper transcription is single-threaded (1.5x real-time on M-series Mac). Could run 2 whisper processes concurrently to use multiple cores.
- **Stage 8 (entity resolution + analytics):** sequential ops; some Python steps parallelize (graph computation per chunk).
- **Stage 9 (RAG ingest):** sequential.

When concurrency is active, set `concurrency_active: <int>` in heartbeat metrics so the viz reflects fan-out.

### External API rate limits

- **PubMed:** 3 req/sec without API key, 10 req/sec WITH key. Check `PUBMED_API_KEY` env var. To get a key: register at NCBI, then settings → API Key Management (free; see `~/Winnie/config/environment` for env-var conventions).
- **OpenAlex:** ~10 req/sec sustainable, 100K req/day free. No key required.
- **ORCID:** ~10 req/sec sustainable. No key required.
- **Listen Notes:** check `LISTEN_NOTES_API_KEY`. Free tier 10K req/month.
- **News API:** check `NEWS_API_KEY`. Free tier 100 req/day.
- **LinkedIn / X / Instagram:** no public API; conservative scrape limits via Playwright. Aggressive scraping leads to account flags.

## Constraints

- Per-call context budget: 200K tokens
- Per-call turn budget: 50 turns
- Default model: Sonnet; escalate to Opus 4.7 if planning complexity warrants
- Track run-log via memory-orchestration; never log directly

## Output contract

When the run completes (or pauses for review):

```yaml
run_id: <id>
phase: 1 | 2 | 3 | 4 | 5
status: completed | paused | failed
current_stage: <stage number where stopped>
summary_stats:
  entities_persisted_by_type: {publication: 245, person: 1, ...}
  assets_acquired: 312
  transcripts_generated: 47
  citations_indexed: 1024
  total_runtime_minutes: 48
  total_tokens_estimated: 1200000
  budget_hits: 0
deliverable_paths:
  vault_root: <path>
  rag_store: <path>
  analytics_dir: <path>
  deliverable_dir: <path or null>
verifications:
  - "Bash ls -la output for each major directory"
  - "sqlite3 entity counts"
next_step: <human-readable: e.g., "Run Phase 2 if approved by Laura's team">
```

## Tools available

- Agent (to dispatch all 5 subagents)
- Read, Write (only for run summary; never for raw content)
- Bash (verification commands, init wrapper invocation, sqlite3 SELECT for counts)

## Telemetry (real-time + at run end)

These agents do hours of background work. Real-time observability is critical because "orchestrator stuck for 30 min on a slow API" looks identical from outside to "orchestrator broken." Emit telemetry at three cadences: stage transitions (per stage), heartbeats (every 60s), and run-end summary.

### Stage transitions

Emit at the start and end of each pipeline stage. Lets the viz show "Phase 1 of 5, Stage 6 of 10" at a glance.

```bash
# At start of each stage:
~/Winnie/bin/hfo-log --event stage_started \
  --skill client-content-inventory --correlation-id "<run_id>" \
  --metrics '{"client_slug": "<slug>", "phase": <int>, "stage": <int>, "stage_name": "<seed_owned_property_sweep|per_person_publication_discovery|...>"}'

# At end of each stage:
~/Winnie/bin/hfo-log --event stage_completed \
  --skill client-content-inventory --correlation-id "<run_id>" \
  --metrics '{"client_slug": "<slug>", "phase": <int>, "stage": <int>, "stage_name": "<...>", "duration_s": <float>, "entities_persisted_in_stage": <int>, "status": "ok|partial|failed"}'
```

### Heartbeats (every 60 seconds while active)

Emit a `heartbeat` event before each subagent dispatch and at least every 60s while waiting on subagent responses. This is the signal that distinguishes "actively working" from "hung." Include current activity in metrics so the viz shows real-time state.

```bash
~/Winnie/bin/hfo-log --event heartbeat \
  --skill client-content-inventory --correlation-id "<run_id>" \
  --metrics '{"client_slug": "<slug>", "phase": <int>, "current_stage": <int>, "current_activity": "<one-line: dispatching content-research target=person_publications batch=2 offset=25>", "last_persist_at": "<ISO>", "batches_completed_count": <int>, "elapsed_seconds": <int>}'
```

### Run-end summary (the dept_completed event)

When a Phase / stage / full pipeline run completes (ok, partial, paused, or failed), emit a `dept_completed` event so the HFO invocation ledger captures the orchestrator's overall outcome. This is the top-level event for client-inventory work; the 5 subagent events nest underneath via shared `correlation_id`.

```bash
~/Winnie/bin/hfo-log \
  --event dept_completed \
  --agent client-content-inventory \
  --department research \
  --entity ccg \
  --status <ok|partial|paused|failed> \
  --correlation-id "<run_id>" \
  --metrics '{"client_slug": "<slug>", "phase": <1-5>, "current_stage": <1-10>, "run_id": "<run_id>", "stages_completed": [<list>], "entities_persisted_total": <int>, "entities_by_type": {"person": <int>, "publication": <int>, "project": <int>, "media-mention": <int>, "amplification": <int>, "speaking-engagement": <int>, "award-received": <int>, "event": <int>, "award-given": <int>, "patent": <int>, "public-presence": <int>, "citation": <int>, "content-asset": <int>}, "assets_acquired": <int>, "transcripts_generated": <int>, "citations_indexed": <int>, "total_runtime_minutes": <int>, "tokens_estimated": <int>, "budget_hits": <int>}'
```

The `correlation_id` must equal the `run_id` so all subagent events from this run cluster together in the viz Chains tab. The 5 subagents (memory-orchestration, content-research, content-acquisition, content-processing, content-analysis) all emit `skill_completed` with the same `--correlation-id "<run_id>"`, producing a multi-touch chain visible in the viz.

Required even on partial or failed runs. Never block real work on telemetry.
