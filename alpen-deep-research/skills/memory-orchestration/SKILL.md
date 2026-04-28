---
name: memory-orchestration
description: >
  USE THIS SKILL whenever a content-heavy skill run (e.g., client-content-
  inventory) needs to persist entities, manage per-run state, build or
  query the SQLite index, write run-log/dedup-cache/validator-flags
  ledgers, or retrieve context-batches for downstream subagents. Owns
  state files; delegates vault-wide work to HFO memory-management.
  Trigger phrases include: 'persist these entities', 'load state for
  this client run', 'index these markdown files', 'retrieve context for
  this batch', 'checkpoint the run', 'resume from state', 'compute
  analytics from index', 'append to run-log', 'dedup-cache lookup',
  'persist these PubMed records', 'flag this for validator review',
  'rehydrate the SQLite index'. Common in CCG, Center for BrainHealth,
  Krystal, Alpen Tech content-inventory pipelines. CRITICAL: every
  claim of file creation must be backed by an actual Write tool call;
  use canonical lowercase paths (e.g., 'cbh/' not 'CBH/'); kebab-case
  entity_type values verbatim from schema YAMLs. Always use this skill
  when persistence/state/indexing for a per-client content run is the
  goal — do NOT pick HFO memory-management (that's vault-wide) or
  content-analysis (that's analytics) when it's per-run state work.
---

# memory-orchestration

## CRITICAL RULES (NON-NEGOTIABLE)

These rules supersede any other guidance in this SKILL. Violations are correctness bugs that produce hallucinated output.

1. **Every claim of action MUST be backed by an actual tool call.** Do not narrate or describe creating files. USE the Write tool. USE the Bash tool. If a tool call is required to fulfill the task, you MUST issue the tool call, not describe what you would do.

2. **Verify every file write.** After every Write tool call, use the Read tool or `ls -la` via Bash to confirm the file exists at the expected path with the expected content. Include the verification output in your run-log entries.

3. **Use exact paths from inputs.** Do not normalize, reformat, or lowercase/uppercase paths. The `state_root` path is lowercase by convention (`~/Library/Application Support/Client-Inventories/cbh/`). The `vault_root` path uses the vault's case (`My Drive/Client-Inventories/CBH/`). Preserve the case provided in inputs exactly.

4. **macOS case-insensitivity warning.** Default macOS volumes are case-insensitive. `CBH/` and `cbh/` resolve to the same directory but display whichever case was used last in writes. ALWAYS use the canonical lowercase form for state paths (`cbh/` not `CBH/`) to avoid orphaning data in subsequent runs.

5. **Return failure when actions fail.** If you cannot create a file, persist a record, or invoke a subagent, return `status: failed` with explicit error details. Do not fabricate success. Returns must reflect reality.

6. **Atomic writes.** Write to `<path>.tmp` first, then rename via Bash `mv`. Never partial writes.

7. **Idempotency.** Running an operation twice with the same inputs must produce the same final state. Check for existing files before creating; merge rather than overwrite for ledgers (run-log.jsonl, dedup-cache.json, validator-flags.json).

8. **JSON Lines append semantics for run-log.jsonl.** New entries get appended as one JSON object per line. Use Bash `cat >>` or read-existing-then-Write-with-append-content. Never overwrite the whole file.

9. **Schema-correct entity_type values (NON-NEGOTIABLE).** SQLite `entity_type` column MUST exactly match the `entity_type` field in the corresponding schema YAML at `<vault_root>/_shared/entity-schemas/<entity_type>.yaml`. Use kebab-case schema names: `person`, `project`, `publication`, `citation`, `public-presence`, `media-mention`, `speaking-engagement`, `award-received`, `cbh-hosted-event`, `cbh-sponsored-award`, `patent`, `content-asset`. NEVER use shortened forms (`award` instead of `award-received`), underscores (`media_mention` instead of `media-mention`), or invented variations (`org_channel` instead of `public-presence`). Real bug: Stage 2 vs Stage 4 mismatch in CBH Phase 1 caused 6 distinct values to appear for what should have been 4 entity types; required manual SQLite normalization. Lookup the schema entity_type field BEFORE persisting any record; use that value verbatim.

## Purpose

You are the operational state manager for content-heavy skills. You own:
- Per-run state files (`<state_root>/_state/inventory-state.json`, `dedup-cache.json`, `validator-flags.json`, `run-log.jsonl`)
- The SQLite index at `<state_root>/_index.sqlite`
- Dispatch coordination back to the orchestrator after persistence completes

You do NOT own:
- The Drive-synced markdown content (the orchestrator and content-* subagents write that directly via the Write tool)
- The RAG store internals (you trigger ingest via HFO memory-management department, but don't operate the store)
- Vault-wide MOC generation or knowledge-base maintenance (HFO memory-management department concern)

## Operations

### op=init

**Purpose:** Initialize state for a new run. Idempotent.

**Inputs:**
- `client_slug`: lowercase string (e.g., "cbh"). MUST be lowercase.
- `state_root`: absolute path (e.g., `/Users/philhoward/Library/Application Support/Client-Inventories/cbh/`). MUST end with the lowercase client_slug.
- `vault_root`: absolute path to Drive-mounted vault (e.g., `/Users/.../My Drive/Client-Inventories/CBH/`).
- `run_id`: unique identifier for this run.
- `phase`: integer (1, 2, 3, 4, or 5).

**Required tool calls (execute in order; do not skip):**

1. **Bash tool: ensure state directory exists**

```
mkdir -p '<state_root>/_state'
```

2. **Bash tool: ensure SQLite is initialized**

```
test -f '<state_root>/_index.sqlite' || python3 ~/Winnie/lib/client-inventory/init_sqlite.py '<state_root>/_index.sqlite'
```

3. **Read tool: check if inventory-state.json already exists**

Path: `<state_root>/_state/inventory-state.json`

If exists: read its content, preserve `started_at` and `batches_completed`, update `current_phase` and `last_modified_at`.
If not exists: create new with `started_at = <current ISO timestamp>`, `batches_completed = []`.

4. **Write tool: create or update inventory-state.json**

Path: `<state_root>/_state/inventory-state.json`

Content (JSON, formatted):
```json
{
  "run_id": "<run_id>",
  "client_slug": "<client_slug>",
  "started_at": "<ISO timestamp>",
  "current_phase": <phase>,
  "current_stage": null,
  "batches_completed": [],
  "last_modified_at": "<ISO timestamp>"
}
```

5. **Bash tool: append init event to run-log.jsonl**

```
echo '{"timestamp": "<ISO>", "subagent": "memory-orchestration", "op": "init", "run_id": "<run_id>", "status": "success"}' >> '<state_root>/_state/run-log.jsonl'
```

6. **Bash tool: verify both files exist**

```
ls -la '<state_root>/_state/'
```

The output MUST show `inventory-state.json` and `run-log.jsonl` with non-zero size. If not, return `status: failed`.

7. **Return:**

```yaml
op: init
status: success | failed
summary:
  run_id: <run_id>
  client_slug: <client_slug>
  state_root: <state_root>
  sqlite_path: <state_root>/_index.sqlite
  rag_path: ~/Winnie/data/client-inventories/<client_slug>/rag.db
  state_files: [inventory-state.json, run-log.jsonl]
  ls_output: <verbatim ls output from step 6>
errors: []  # populated if status=failed
```

### op=persist_batch

**Purpose:** Persist a batch of records produced by a content-* subagent.

**Inputs:**
- `batch`: list of records, each with `entity_type`, `fields`, `source_of_record`
- `batch_id`: unique identifier for this batch
- `subagent`: name of the subagent that produced the batch (for run-log)
- `client_slug`, `state_root`, `vault_root`: same as op=init

**Required tool calls (execute in order; do not skip):**

For each record in `batch`:

1. **Compute slug.** Deterministic from canonical_name, DOI, or other natural key per entity type. Lowercase, hyphenated.

2. **Read dedup cache:** `<state_root>/_state/dedup-cache.json` (use Read tool).
   - If file doesn't exist, treat dedup set as empty.
   - If slug is in the dedup set: log dedup-hit, skip to next record. Do NOT write.

3. **Build YAML frontmatter** matching the entity-type schema at `<vault_root>/_shared/entity-schemas/<entity_type>.yaml`. Include all required fields plus the validator_status field (default: unreviewed).

4. **Write tool: create entity record markdown file.**
   - Path: `<vault_root>/<entity_type_folder>/<slug>.md`
   - Folder mapping: person -> people/, project -> projects/, publication -> publications/, citation -> citations/, public-presence -> public-presence/, media-mention -> media-mentions/, speaking-engagement -> speaking-engagements/, award-received -> awards-received/, cbh-hosted-event -> events/, cbh-sponsored-award -> awards-given/, patent -> patents/, content-asset -> (no separate file; tracked only in SQLite)
   - Content: YAML frontmatter then body section with summary or full content as appropriate

5. **Bash tool: insert SQLite row**

```
sqlite3 '<state_root>/_index.sqlite' "INSERT OR REPLACE INTO entities (slug, entity_type, canonical_name, md_path, validator_status, discovered_at, last_modified_at, source_of_record, metadata) VALUES ('<slug>', '<entity_type>', '<canonical_name>', '<md_path>', 'unreviewed', '<ISO>', '<ISO>', '<json escaped>', '<json escaped>');"
```

6. **Update dedup cache.** Read `<state_root>/_state/dedup-cache.json`, add slug, Write back.

After all records in batch processed:

7. **MANDATORY post-persist verification (DO NOT SKIP).** SQLite divergence from vault files is a known failure mode. After every batch, verify SQLite count matches vault file count for the entity type:

   ```bash
   # For each entity_type touched in the batch:
   FILE_COUNT=$(ls '<vault_root>/<entity_type_folder>/' | wc -l | tr -d ' ')
   SQL_COUNT=$(sqlite3 '<state_root>/_index.sqlite' "SELECT COUNT(*) FROM entities WHERE entity_type='<entity_type>';")
   if [[ "$FILE_COUNT" != "$SQL_COUNT" ]]; then
     # Divergence detected — emit hallucination_detected and try to reconcile via INSERT OR IGNORE pass
     echo "WARN: $entity_type vault=$FILE_COUNT sqlite=$SQL_COUNT" >&2
     # Reconcile: walk vault, INSERT OR IGNORE for any slug not in SQLite
   fi
   ```

   Real bug: CBH Phase 1 Stage 4.5 wrote 4 files to disk but didn't update SQLite. Manual Python sync was required after. This verification step catches the divergence at the source.

8. **Bash tool: append batch summary to run-log.jsonl**

```
echo '{"timestamp": "<ISO>", "subagent": "<subagent>", "op": "persist_batch", "items_processed": <int>, "dedup_hits": <int>, "batch_id": "<batch_id>", "wall_clock_seconds": <float>, "vault_count": <int>, "sqlite_count": <int>, "divergence_detected": <bool>, "status": "success"}' >> '<state_root>/_state/run-log.jsonl'
```

9. **Return:**

```yaml
op: persist_batch
status: success | partial | failed
summary:
  persisted: <int>
  deduped: <int>
  paths: [list of md files written]
  batch_id: <batch_id>
  vault_sqlite_match: <bool>  # MANDATORY — set false if divergence and reconciliation needed
errors: []  # any per-record failures
```

### op=get_state

**Purpose:** Return current run state.

**Inputs:**
- `run_id`
- `state_root`

**Required tool calls:**

1. **Read tool:** `<state_root>/_state/inventory-state.json`
2. **Bash tool:** count entities by type from SQLite
   ```
   sqlite3 '<state_root>/_index.sqlite' "SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type;"
   ```
3. **Bash tool:** tail of run-log
   ```
   tail -n 5 '<state_root>/_state/run-log.jsonl'
   ```

4. **Return:** structured state with counts and recent activity. Reflect what was actually read; do not fabricate.

### op=mark_validated

**Purpose:** Persist validator feedback from CBH staff.

**Inputs:**
- `validations`: list of `{slug, status, notes}` tuples
- `state_root`, `vault_root`

**Required tool calls:**

For each validation:

1. **Read tool:** the entity markdown file at `<vault_root>/<entity_type>/<slug>.md`
2. **Edit tool:** update the YAML frontmatter `validator_status` and `validator_notes` fields
3. **Bash tool:** update SQLite row
   ```
   sqlite3 '<state_root>/_index.sqlite' "UPDATE entities SET validator_status='<status>' WHERE slug='<slug>';"
   ```

After all validations:

4. **Read+Write:** update `<state_root>/_state/validator-flags.json` ledger
5. **Bash tool:** append to run-log.jsonl

6. **Return** counts and confirmations.

### op=resync_from_vault

**Purpose:** Sync SQLite index from current state of markdown files in the vault.

**Required tool calls:**

1. **Bash tool:** find all entity markdown files
   ```
   find '<vault_root>' -name '*.md' -not -path '*/_*' -not -path '*/Archive/*'
   ```
2. **For each file:** Read frontmatter, parse, INSERT OR REPLACE into SQLite
3. **Return** counts.

### op=validate_cbh_association

**Purpose:** Audit Person records for missing or incomplete `cbh_association` blocks. Used in Phase 2 pre-flight.

**Required tool calls:**

1. **Bash tool:** query Person records from SQLite
2. **For each:** Read markdown frontmatter, inspect `cbh_association` block
3. **Return** list of records with missing or incomplete association data.

### op=finalize_run

**Purpose:** Trigger end-of-run RAG ingest and produce summary stats.

**Inputs:**
- `run_id`, `client_slug`, `state_root`
- `rag_config_path`: e.g., `~/Winnie/rag/client-inventory-cbh.yaml`

**Required tool calls:**

1. **Bash tool:** count entities per type from SQLite, count ContentAssets, count transcripts.
2. **Agent tool:** dispatch HFO memory-management department for RAG ingest
   - subagent_type: "memory-management"
   - prompt: "rag_ingest config_path=<rag_config_path>. Use the existing ~/Winnie/rag/ingest.py pattern with the provided config. Return ingest summary."
3. **Bash tool:** append finalize event to run-log.jsonl
4. **Return:** summary stats including counts, RAG ingest status, run-log tail.

## Constraints

- Per-call context budget: 50K tokens
- Per-call turn budget: 50 turns
- Always atomic file writes (`.tmp` then `mv`)
- Always idempotent
- Always log to run-log.jsonl before returning, even on failure
- Never load full markdown content into context; use file paths only

## Tools available

- Read, Write, Edit
- Bash (for file ops, SQLite queries, run-log appends, init wrapper invocation)
- Agent (only for delegating to HFO memory-management department on op=finalize_run)

## Output contract

Always return a structured summary, never raw record content. Format:

```yaml
op: <op>
status: success | partial | failed
summary:
  <op-specific keys>
errors: []  # populated if status != success
verifications: []  # list of ls/cat outputs proving the work was done
```

The `verifications` field is mandatory: include the actual output of the verification commands (ls, cat, sqlite3 SELECT) that prove the operations succeeded.

## Telemetry (per-op + verification + validator events)

Memory-orchestration is the persistence-critical layer. Telemetry emphasizes verification (catch hallucinations) and validation (track CBH staff feedback).

### Anti-hallucination verification check (after every persist)

After every `op=persist_batch`, run an automated verification: count files written on disk, count SQLite rows inserted, compare to claimed counts. If mismatch, emit `hallucination_detected` event. The Phase 0.5 hardening prevents this in normal cases; this runtime check catches regressions.

```bash
# After each persist_batch, before emitting skill_completed:
ACTUAL_FILES=$(find <vault_root>/<entity_type>/ -newer <timestamp> -name '*.md' -o -name '*.json' | wc -l)
ACTUAL_ROWS=$(sqlite3 <state_root>/_index.sqlite "SELECT COUNT(*) FROM entities WHERE last_modified_at >= '<timestamp>';")
CLAIMED_COUNT=<from-batch-result>

if [ "$ACTUAL_FILES" != "$CLAIMED_COUNT" ] || [ "$ACTUAL_ROWS" != "$CLAIMED_COUNT" ]; then
  ~/Winnie/bin/hfo-log --event hallucination_detected \
    --skill memory-orchestration --correlation-id "<run_id>" \
    --metrics "{\"claimed\": $CLAIMED_COUNT, \"actual_files\": $ACTUAL_FILES, \"actual_rows\": $ACTUAL_ROWS, \"batch_id\": \"<batch_id>\", \"op\": \"persist_batch\"}"
fi
```

This is a non-blocking diagnostic. The skill_completed event still emits with corrected metrics from the actual disk state (not claimed state).

### Validator-activity events (when op=mark_validated)

When CBH staff use the spreadsheet to flag rows verified/disputed/false-positive, the orchestrator dispatches op=mark_validated. Each validation emits a `validation_event` so the viz can track validator throughput, false-positive rates by entity type, and per-validator productivity.

```bash
# Per validation (one event per status change):
~/Winnie/bin/hfo-log --event validation_event \
  --skill memory-orchestration --correlation-id "<run_id>" \
  --metrics '{"client_slug": "<slug>", "entity_type": "<type>", "entity_slug": "<slug>", "validator_status_change": "<unreviewed -> verified|disputed|false-positive>", "validator_identity": "<email or name if known>", "notes_length": <int>}'

# Then per batch of validations, the standard op=mark_validated skill_completed:
~/Winnie/bin/hfo-log --event skill_completed \
  --skill memory-orchestration --correlation-id "<run_id>" \
  --metrics '{"op": "mark_validated", "validated_count": <int>, "disputed_count": <int>, "false_positive_count": <int>, "client_slug": "<slug>"}'
```

### Standard per-op `skill_completed` event

After every op completes (success or failure), emit a `skill_completed` event via `hfo-log` so the HFO invocation ledger captures adoption, reliability, and value metrics.

```bash
~/Winnie/bin/hfo-log \
  --event skill_completed \
  --skill memory-orchestration \
  --department memory \
  --entity ccg \
  --status <ok|partial|failed> \
  --correlation-id "<run_id>" \
  --metrics '{"client_slug": "<slug>", "op": "<op>", "items_persisted": <int>, "dedup_hits": <int>, "run_id": "<run_id>", "duration_s": <float>}'
```

The `entity` is the principal performing the work (typically `ccg` for client-inventory engagements). The `client_slug` (e.g., `cbh`) goes in metrics. This separation lets the viz roll up per-entity activity while still capturing per-client volume.

Required even on failure: emit with `status: failed` and include error class in metrics. Never block real work on telemetry; if `hfo-log` fails, log to stderr and continue.
