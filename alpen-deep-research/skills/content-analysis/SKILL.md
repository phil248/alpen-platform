---
name: content-analysis
description: >
  USE THIS SKILL whenever a content-inventory run needs entity resolution,
  deduplication, author name resolution, citation-graph or co-authorship
  network construction, theme classification, or analytics computation
  (CSV/JSON outputs with provenance sidecars). Trigger phrases include:
  'dedupe these entities', 'build citation graph', 'compute co-authorship
  network', 'classify themes', 'run analytics', 'resolve entities',
  'compute distributions', 'cluster authors', 'normalize author names',
  'compute the network graph', 'theme classification on abstracts',
  'analytics rollup for this client'. Common in CCG, Center for
  BrainHealth, Krystal speaking research, Alpen Tech research deliverables.
  CRITICAL: every claim of analytics output must be backed by an actual
  file written; never fabricate counts or graphs. Always use this skill
  when the request is about deriving structure from already-collected
  content — do NOT pick content-research (that discovers) or
  memory-orchestration (that persists raw records) when analytics is
  the goal.
---

# content-analysis

## CRITICAL RULES (NON-NEGOTIABLE)

1. **Every claim of analytics output MUST be backed by an actual file on disk.** After every analytic operation, verify the output CSV/JSON exists at the expected path via Bash `ls -la`. Never return analytics file paths you did not actually create.

2. **Use real computation tools.** SQLite queries MUST go through Bash `sqlite3`. Graph computation MUST use Python with networkx. Theme classification MUST use actual LLM calls (your own model context, with abstracts in the prompt). Do not narrate computations.

3. **Read from disk; don't reason from claimed counts.** When you need entity counts, query SQLite. When you need publication abstracts, read the markdown files. Don't fabricate counts or claim entities exist that you didn't verify. **LLM-written dashboards are FORBIDDEN** (added 2026-05-07; audit finding #2): dashboard counts MUST be computed by `op=build_verified_dashboard` (deterministic Python script reading filesystem + SQLite). Never narrate-and-synthesize counts from prior agent claims.

4. **Atomic writes for analytics outputs.** Write to `<path>.tmp`, then `mv`. Verify file exists with non-zero size.

5. **Return failure when computations fail.** If networkx graph construction fails, if SQLite query returns no rows, if theme classification produces no labels: return `status: failed` with explicit reason. Do not fabricate analytics with empty inputs.

6. **Provenance per analytic.** Each output file should be accompanied by a sibling `<filename>.provenance.json` documenting the input source (which SQLite table, which markdown files, what filter), the computation method, and the timestamp.

## Purpose

Read accumulated entity records from the per-client vault and SQLite index. Apply entity resolution to deduplicate. Resolve author names against the People Identity Vector. Build citation graphs and co-authorship networks. Classify themes via LLM-assisted analysis on abstracts. Produce computed analytics outputs (CSV, JSON) for the deliverable package.

This subagent reads from disk and writes to disk; it does not need to keep the full corpus in context.

## Operations

### op=build_verified_dashboard (added 2026-05-07; audit finding #2)

Generate the disk-anchored dashboard at the end of every run. **This is the canonical source of truth for entity counts.** LLM-written dashboards are forbidden; this op is deterministic Python.

**DISPATCH TO SCRIPT — DO NOT replicate the protocol inline.** Stage 10 calls one function:

```python
from lib.content_analysis.build_verified_dashboard import build_dashboard
result = build_dashboard(
    inventory_root='<vault_root>',
    rag_db_path='~/Winnie/data/client-inventories/<client>/rag.db',
    output_md_path='<vault_root>/_deliverable/<date>-verified-dashboard.md',
)
# returns: {counts_by_kind, asset_coverage, rag_state, orcid_truth_check, output_md_path}
```

Or via Bash:

```bash
~/Winnie/rag/venv/bin/python -m lib.content_analysis.build_verified_dashboard \
  --inventory-root '<vault_root>' \
  --rag-db ~/Winnie/data/client-inventories/<client>/rag.db \
  --output '<vault_root>/_deliverable/<date>-verified-dashboard.md'
# Add --skip-orcid for offline mode (no live pub.orcid.org calls).
```

The script does ALL of: per-kind JSON counts, asset coverage (transcript/pdf/html_local_path), RAG chunk counts + distinct paths per source_kind, per-ORCID truth-check (curl `pub.orcid.org/<orcid>/works` and compute delta_pct vs inventory pubs), atomic write of MD + `<...>.provenance.json` sidecar. Output is idempotent. Do NOT synthesize counts in markdown directly; the script is the protocol.

### op=compute_amplification_attribution (added 2026-05-07; audit finding #12)

**DISPATCH TO SCRIPT — DO NOT inline-Bash + Haiku NER.** One Python call:

```python
from lib.content_analysis.amplification_attribution import compute_amplification_attribution
result = compute_amplification_attribution(
    inventory_root='<vault_root>',
    output_csv_path='<vault_root>/_deliverable/<date>-amplification-attribution.csv',
    output_md_path='<vault_root>/_deliverable/<date>-amplification-attribution.md',
)
# returns: {records, complete_chains, by_outlet, by_person}
```

Or via Bash:

```bash
~/Winnie/rag/venv/bin/python -m lib.content_analysis.amplification_attribution \
  --inventory-root '<vault_root>' \
  --output-csv  '<vault_root>/_deliverable/<date>-amplification-attribution.csv' \
  --output-md   '<vault_root>/_deliverable/<date>-amplification-attribution.md'
# Add --skip-ner to aggregate existing fields only (no LLM calls).
```

The script iterates `amplifications/*.json`, locates the matching v2 transcript at `_assets/transcripts/<slug>*.html-extracted-v2.md` (fallback v1, then any v-less), shells out to `claude -p --model haiku --output-format text` with a strict-JSON NER prompt, parses the response (tolerant of markdown fences and preface/postface), updates the amplification JSON in-place (only fills missing fields; never overwrites curator-set values), and writes the CSV + MD aggregates atomically. The script is the protocol.

### op=compute_citation_graph (extended 2026-05-07; audit finding #10 — see hook below)

(Existing description follows; extension: also write `_analytics/cited-by-network.json` capturing the cited_by graph, in addition to the existing citation-counts.csv and citation-trajectory.csv outputs. The cited_by network is the OpenAlex `/works/<id>/cited-by` query pattern aggregated across all client-led publications, output as a node-link JSON.)

### op=resolve_entities

Run dedup pass across all entity types in the corpus.

**Schema-drift sweep (REQUIRED pre-pass; added 2026-05-07; audit finding #15):** before the main dedup pass, normalize known divergences:
- Person records that use `title:` instead of `canonical_name:` → rewrite frontmatter to use `canonical_name:`.
- Publication records where `authors` is a comma-separated string → split and rewrite as JSON array.
- Any kebab-case enum mismatches → normalize to schema YAML's exact spelling (e.g., `media_mention` → `media-mention`).
- Reject and re-flag any record whose top-level structure is a `publications: [...]` list (roll-up antipattern; see CRITICAL RULE #8 in client-content-inventory). Move them to `_archive/<original-path>` and emit a `validator-flags` event.

This pre-pass eliminates schema drift before merge logic runs; without it, dedup misses records whose name/author fields diverge from canonical.

**Merge order (added 2026-05-07):** for people, MERGE BY ORCID FIRST, then by name_variants overlap, then by name-equality. ORCID is deterministic and authoritative; name-equality is the last resort.

**Required tool calls:**

1. **Bash sqlite3:** query all entities of each type, capture slug + canonical_name + source_of_record
   ```
   sqlite3 '<state_root>/_index.sqlite' "SELECT slug, entity_type, canonical_name, source_of_record FROM entities;"
   ```
2. **For publications:**
   - Build a dedup index keyed by DOI (authoritative)
   - For records without DOI, fuzzy-match on title (Levenshtein < 0.1) + first author + year
   - Use OpenAlex ID, PMID as secondary keys
3. **For people:**
   - Match by ORCID first
   - Then by canonical_name + affiliation overlap
   - Use name_variants to bridge "S. Chapman" / "Sandra Bond Chapman"
4. **For projects:**
   - Match by grant_number first
   - Then by name + lead_pi + period overlap
5. **For each merge action:**
   - Use Bash sqlite3 UPDATE to change md_path of duplicates to point to canonical
   - Use Bash mv to delete duplicate markdown files (or move to `_archive/`)
   - Append merge action to `<state_root>/_state/dedup-actions.jsonl`

**Output:** dedup statistics, merge action log path, count of remaining unique entities.

### op=compute_citation_graph

Build the citation graph for client-led publications.

**Required tool calls:**

1. **Bash sqlite3:** query Publication entities where `cbh_attribution_basis IN ('cbh-led-project', 'cbh-tenured-author')`
2. **For each publication, WebFetch OpenAlex citations endpoint:**
   ```
   https://api.openalex.org/works/W<openalex_id>/cited-by
   ```
3. **For each citing work returned:**
   - Create a Citation entity record (markdown file + SQLite row)
   - Persist via memory-orchestration (op=persist_batch)
4. **Compute citation analytics:**
   ```python
   import pandas as pd
   import sqlite3
   conn = sqlite3.connect('<state_root>/_index.sqlite')
   df = pd.read_sql("SELECT * FROM entities WHERE entity_type='citation'", conn)
   # Top-cited papers
   top_cited = df.groupby('cited_pub_id').size().sort_values(ascending=False).head(20)
   top_cited.to_csv('<vault_root>/_analytics/citation-counts.csv')
   # Trajectory over time
   df['citation_year'] = df['metadata'].apply(lambda x: json.loads(x).get('citation_year'))
   trajectory = df.groupby(['cited_pub_id', 'citation_year']).size().unstack(fill_value=0)
   trajectory.to_csv('<vault_root>/_analytics/citation-trajectory.csv')
   ```
5. **Bash ls -la:** verify outputs exist at `<vault_root>/_analytics/citation-counts.csv` and `citation-trajectory.csv`

### op=compute_coauthor_network

Build co-authorship network from publications.

**Required tool calls:**

1. **Bash sqlite3:** read all Publication entities
2. **For each publication:** read markdown frontmatter to get authors list
3. **Python with networkx:**
   ```python
   import networkx as nx
   import json
   G = nx.Graph()
   # Add nodes for each Person; edges for each co-authorship pair
   # ... compute internal density, top external collaborators
   nx.write_gml(G, '<vault_root>/_analytics/coauthor-network.gml')
   # Also write JSON for visualization
   data = nx.node_link_data(G)
   with open('<vault_root>/_analytics/coauthor-network.json', 'w') as f:
       json.dump(data, f)
   ```
4. **Bash ls -la:** verify outputs
5. **Cytoscape HTML deliverable (added 2026-05-07; audit finding #11):** in addition to the GML and JSON outputs, also write a self-contained `<vault_root>/_deliverable/<date>-network-graph.html` that loads Cytoscape.js (CDN-hosted) and embeds the JSON inline. Browser-openable, no server required. This was hand-built today; making it a default deliverable.

### op=classify_themes

Apply theme tags to publications and other content.

**Required tool calls:**

1. **Bash sqlite3:** query Publication entities without theme_tags populated
2. **Read taxonomy:** Read tool on `<vault_root>/_shared/taxonomy/themes.yaml`
3. **For each batch of 20 publications:**
   - Read their markdown files, collect abstracts
   - Construct LLM prompt: "Given the 10 themes (with descriptions): {...}, classify each abstract by which themes apply (multi-label). Return JSON with abstract_id -> [theme_slugs]."
   - Issue actual LLM call (your own model context can do this directly; you're an LLM)
   - Parse the response into theme_tag updates
4. **For each result:**
   - Edit the publication markdown frontmatter to add theme_tags
   - Update SQLite metadata
5. **Bash ls -la and sqlite3 SELECT:** verify a sample of records have theme_tags populated

### op=compute_distributions

Compute the analytics package: theme distribution, audience reach, channel coverage, influence ripples.

**Required tool calls:**

1. **Bash sqlite3:** query enriched data (theme_tags, audience_tag, venue, etc.)
2. **Python pandas:**
   ```python
   import pandas as pd
   import sqlite3
   import json
   conn = sqlite3.connect('<state_root>/_index.sqlite')
   df = pd.read_sql("SELECT * FROM entities WHERE entity_type='publication'", conn)
   # Parse metadata JSON
   df['theme_tags'] = df['metadata'].apply(lambda x: json.loads(x).get('theme_tags', []))
   df['audience_tag'] = df['metadata'].apply(lambda x: json.loads(x).get('audience_tag'))
   # Theme distribution
   df_themes = df.explode('theme_tags').groupby(['theme_tags', 'audience_tag']).size().unstack(fill_value=0)
   df_themes.to_csv('<vault_root>/_analytics/theme-distribution.csv')
   # Audience reach
   audience = df.groupby('audience_tag').size()
   audience.to_csv('<vault_root>/_analytics/audience-reach.csv')
   # Channel coverage
   channels = df.groupby('venue_type').size()
   channels.to_csv('<vault_root>/_analytics/channel-coverage.csv')
   # Influence ripples (top-cited papers + their cited-by chain)
   # ... write to influence-ripples.json
   ```
3. **Bash ls -la:** verify all 4 output files

## Output contract

```yaml
op: <op>
status: success | partial | failed
analytics_files:
  - path: <path>
    bytes: <int>  # MUST match actual file size
    rows: <int>   # for CSVs
summary_stats:
  <op-specific keys>
errors: []
verifications:
  - "ls -la for each output file"
  - "sample query results showing data was actually written"
```

## Constraints

- Per-call context budget: 300K tokens
- Per-call turn budget: 100 turns (graph computation may iterate)
- Read-from-disk pattern: SQLite query and markdown read; never load full corpus into context at once
- LLM theme classification: batch 20 abstracts per call max
- Always write outputs to disk; the orchestrator reads paths

## Tools available

- Read, Write
- Bash (Python invocations, SQLite queries, networkx, pandas)
- LLM calls (within your own model context) for theme classification on abstracts

## Telemetry (heartbeat + per-op)

Citation graph build can run minutes-to-hours depending on corpus size. Heartbeats track progress through the work.

### Heartbeat events (every 60s while op in flight)

```bash
~/Winnie/bin/hfo-log --event heartbeat \
  --skill content-analysis --correlation-id "<run_id>" \
  --metrics '{"current_activity": "<one-line: querying OpenAlex citations for pub 47 of 250>", "op": "<op>", "items_processed_so_far": <int>, "elapsed_seconds": <int>}'
```

### Per-op `skill_completed` event

After each analysis op completes, emit a `skill_completed` event via `hfo-log`. The metrics let the viz track adoption per analysis type (dedup vs. citation graph vs. theme classification) so productization decisions know which analytics produce most value per run.

```bash
~/Winnie/bin/hfo-log \
  --event skill_completed \
  --skill content-analysis \
  --department research \
  --entity ccg \
  --status <ok|partial|failed> \
  --correlation-id "<run_id>" \
  --metrics '{"client_slug": "<slug>", "op": "<op>", "analytics_files_written": <int>, "entities_resolved": <int>, "duplicates_merged": <int>, "themes_classified": <int>, "citations_indexed": <int>, "graph_nodes": <int>, "graph_edges": <int>, "duration_s": <float>}'
```

Required even on failure. Never block real work on telemetry.
