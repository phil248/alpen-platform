---
name: content-research
description: >
  USE THIS SKILL whenever Phil or a content-inventory orchestrator needs to
  discover publications, talks, podcasts, op-eds, media mentions, awards,
  or other public content attributable to a client person or org via
  PubMed, OpenAlex, ORCID, NIH RePORTER, Listen Notes, news APIs, and
  tiered web acquisition (HTTP -> Playwright headless -> real Chrome).
  Trigger phrases include: 'search PubMed for these authors', 'find
  publications by Sandra Chapman', 'find publications by Sandi Chapman',
  'discover content for this org', 'ORCID lookup', 'search OpenAlex',
  'find citations for X', 'research a person's publications', 'look up
  this researcher's papers', 'find podcasts featuring Krystal', 'find
  op-eds by this author', 'NIH RePORTER search', 'discover speaking
  engagements'. Common in CCG, Center for BrainHealth, Krystal speaking
  research, Alpen Tech, executive client research. CRITICAL: every
  discovered record must come from an actual tool call; never fabricate
  URLs or DOIs. ALL name variants must be searched (e.g., 'Sandra' AND
  'Sandi' AND last-name-only). Always use this skill for public-source
  content discovery — do NOT pick content-acquisition (that downloads
  known URLs) when the URLs are not yet known.
---

# content-research

## CRITICAL RULES (NON-NEGOTIABLE)

1. **Every discovered record MUST come from an actual tool call.** Do not fabricate publications, URLs, DOIs, or any metadata. If you cannot find content, return an empty list with `next_batch_offset: null` and explicit `failures` entries.

2. **Cite the source per field.** Each record's `source_of_record` dict must accurately reflect which API or fetch tool produced each field. Lying about source_of_record is a correctness bug.

3. **Use real tool calls for every discovery action.** PubMed search MUST use the `mcp__claude_ai_PubMed__search_articles` tool. OpenAlex queries MUST use WebFetch or a Bash curl call against api.openalex.org. ORCID lookups MUST use WebFetch against pub.orcid.org. Do not narrate searches; execute them.

4. **Persist nothing yourself.** Return discovered records to the caller. The orchestrator passes them to memory-orchestration for persistence. Your job is discovery, not storage.

5. **Apply the inclusion rule strictly.** Include only content where the client (or the client-tenured person during their tenure) produced or led the work. Pre-tenure or post-tenure work is OUT. Project-led-by-Stanford-with-CBH-contributing is OUT.

6. **Return failure when sources fail.** If PubMed times out, ORCID returns 404, or a website blocks the fetch, record the failure in `failures` list and continue with whatever you did successfully. Do not silently substitute fake data.

7. **Tier escalation is mandatory.** When HTTP fetch returns near-empty content, you MUST attempt Playwright headless. When Playwright headless fails, you MUST attempt real Chrome (Tier 3) per the design doc fallback strategy. Record the tier used in `source_of_record`.

8. **Iterate ALL name variants (NON-NEGOTIABLE for person-targeted searches).** When searching for a person's content (publications, talks, podcasts, op-eds, media mentions), you MUST issue separate searches for EVERY entry in `person.name_variants` — including informal/colloquial forms (e.g., "Sandi", "Sandy", first-name-only, married-name-only). Search engines and APIs do NOT reliably handle name variants automatically; "Sandra Chapman" and "Sandi Chapman" return DIFFERENT result sets on Google, News API, Listen Notes, YouTube, and most other sources. Real bug: CBH Phase 1 Stage 4 searched "Sandra Chapman" only and found 15 speaking engagements; targeted Sandi-variant searches in Stage 4.5 surfaced additional content (local Dallas press, podcast intros, LinkedIn re-shares). Cost: 3-5x more search calls but typically 30-50% more content discovered. Always run variant searches; mark `source_of_record._variant_used` per record to track which variant produced each discovery.

## Purpose

Discover content attributable to a client organization or person. Apply the inclusion rule. Return deduplicated URLs and metadata. Persist nothing; the orchestrator handles persistence via memory-orchestration.

## Operations (target values)

### target=seed_owned_property_sweep

Comprehensive sweep of client-owned properties. The highest-confidence seed for the rest of the pipeline.

**Required tool calls (in order):**

1. **WebFetch tool:** fetch the client's primary URL (`inputs.client.primary_url`)
   - Extract: people roster, programs, events, news links, press kit links, in-the-media section
2. **WebFetch tool:** fetch each URL in `inputs.client.other_owned_urls`
   - Extract whatever is structured on each page
3. **For each owned channel discovered:** WebFetch and parse
   - LinkedIn org page (Tier 2 likely needed; use Playwright)
   - YouTube channel (Tier 1 may work; fall back to Tier 2)
   - X/Twitter, Instagram, Facebook (likely Tier 2 or 3)
4. **For each person surfaced from the website:** record canonical_name, role title, tenure dates if visible, primary unit, photo URL, bio text
5. **For each project surfaced:** record project name, type, lead PI, period if visible, funding source if visible

**Outputs (returned to orchestrator, NOT persisted):**

```yaml
target: seed_owned_property_sweep
batch_id: <batch_id>
discovered_records:
  - entity_type: person
    fields: {canonical_name, name_variants, role, ...}
    source_of_record: {canonical_name: "centerforbrainhealth.org/our-team", ...}
  - entity_type: project
    fields: {name, type, led_by_cbh: true, ...}
    source_of_record: {name: "centerforbrainhealth.org/research", ...}
  - entity_type: cbh-hosted-event
    fields: {event_name, date, type, ...}
  - entity_type: public-presence
    fields: {platform, url, ...}
  # etc.
next_batch_offset: null  # seed sweep is one-shot
failures: []
tier_distribution: {tier-1-http: <int>, tier-2-playwright-headless: <int>, tier-3-real-chrome: <int>}
verifications:
  - "fetched <url>: <bytes> bytes, <count> people extracted"
  - ...
```

### target=person_publications

Per-person publication discovery. Inputs: `person_canonical_name`, `time_horizon`, `batch_offset`, `batch_size` (adaptive; see below), `cbh_association.tenure_periods`.

**Adaptive batch sizing:**
- For prolific authors (>100 pubs known or expected): use `batch_size=50`
- For typical authors (30-100 pubs): use `batch_size=25`
- For sparse authors (<30 pubs): use `batch_size=15`
- The orchestrator passes the appropriate size based on the person's expected volume from their bio (e.g., Sandra Chapman has 250+ pubs → use 50 once warmed up)

**Required tool calls — BULK FIRST, ENRICH SECOND:**

The single highest-leverage optimization is ORCID's bulk-works endpoint, which returns the author's COMPLETE works list in ONE call. Use this as the primary source; fall back to other sources only for missing fields or pubs not in ORCID. A naive per-pub cross-validation does 5+ API calls per pub × 250 pubs = 1250+ calls per person. Bulk-first pattern does under 10 calls total per person — roughly 100x fewer API calls.

1. **ORCID bulk works (one call returns ALL of author's works):**

   ```
   WebFetch:
     URL: https://pub.orcid.org/v3.0/<orcid_id>/works
     Headers: Accept: application/json
   ```

   This returns up to thousands of works in one response. The response includes group/work-summary structure with put-codes; for each batch, fetch detail in groups of put-codes:

   ```
   WebFetch:
     URL: https://pub.orcid.org/v3.0/<orcid_id>/works/<put_code1,put_code2,...>
     (up to ~50 put_codes per request, comma-separated)
   ```

2. **OpenAlex enrichment for ORCID-listed works** (only fetch what ORCID didn't provide):

   ```
   WebFetch:
     URL: https://api.openalex.org/works?filter=author.orcid:<orcid_id>&per-page=200&cursor=*
   ```

   Cursor-paginate to get full corpus; merge with ORCID list by DOI. OpenAlex provides citation_count, abstract, openalex_id, citing_works that ORCID lacks.

   **Capture author affiliations from authorships array** (mandatory for downstream co-author network classification). OpenAlex returns each work's `authorships` field with structured author info including institutions:

   ```yaml
   # In each publication record, populate:
   authors_with_affiliations:
     - author_name: "Sandra B. Chapman"
       openalex_author_id: "A5044324548"
       orcid: "0000-0002-5244-2068"
       institutions: ["Center for BrainHealth", "University of Texas at Dallas"]
       is_corresponding: true
     - author_name: "Jeffrey S. Spence"
       openalex_author_id: "A..."
       institutions: ["University of Texas at Dallas"]
   ```

   Real bug: CBH Phase 1 Stage 8 found that all author records had empty `affiliation_hint`. Co-author network couldn't classify CBH-internal vs external collaborators without re-querying OpenAlex authorships per publication. Capture during discovery to avoid this.

   **DOI URL-encoding required for special characters.** DOIs with `&`, `+`, `?`, `#`, or other reserved URL characters MUST be percent-encoded before use in API URLs. Real bug: CBH Phase 1 Stage 8 had 1 DOI failure (`10.1207/s15326942dn2501&2_4`) because the unencoded ampersand caused HTTP 400 from OpenAlex. Use `urllib.parse.quote(doi, safe='')` or equivalent before constructing URLs.

3. **PubMed for missing biomedical metadata only:**

   Use `mcp__claude_ai_PubMed__search_articles` ONLY if ORCID + OpenAlex didn't cover a biomedical pub. Don't blanket-call PubMed for every pub. Apply rate limit: 3 req/sec without API key, 10 req/sec WITH API key (check `PUBMED_API_KEY` env var; if set, append `&api_key=$PUBMED_API_KEY` to NCBI URLs).

4. **Skip Semantic Scholar and Google Scholar by default.** Only invoke if the above sources missed pubs the person bio claims (e.g., bio claims "250+ pubs" but you found 200).

**Inclusion-rule application (after gathering, before persistence):**

For each candidate publication:
- Apply tenure-period filter: publication date MUST overlap with at least one entry in `person.cbh_association.tenure_periods`
- Apply CBH-led-project filter: cross-reference with project ledger; the publication's grant_number or funding_source must match a project in the ledger, OR the publication's first-author affiliation must include CBH / UT Dallas
- Set `cbh_attribution_basis` field accordingly: `cbh-led-project` | `cbh-tenured-author` | `cbh-affiliation-listed`

**Output:** publications batch. Set `next_batch_offset = batch_offset + batch_size` if more works exist; null when corpus exhausted.

### target=person_non_publication_content

Per-person discovery: news, podcasts, talks, awards, op-eds, media features. Inputs: `person_canonical_name`, `time_horizon`, etc.

**Required tool calls:**

1. **WebFetch:** News API search by author/quoted-name; capture op-eds and media features
2. **WebFetch:** Listen Notes API for podcast appearances
3. **WebFetch:** YouTube search for talk recordings
4. **For award discovery:** read the person's faculty page or LinkedIn for honors section; cross-reference bestowing-org websites

Apply tenure-period filter on dates where knowable.

### target=org_level_content

Org-level content: events, sponsored awards, patents, public-presence enumeration, third-party media about the client-as-organization.

**Required tool calls:**

1. **WebFetch:** client website events page (full historical depth)
2. **WebFetch:** client website awards-given or recognition page
3. **WebFetch USPTO PatFT:** search by inventor names + assignee; record patents
4. **WebFetch USPTO TSDR:** trademark search for client-named methodologies
5. **WebFetch News API:** third-party media mentions of the client-as-organization
6. **For each owned channel:** deep enumeration (full YouTube channel video list, full podcast feed, etc.)

## Source authority resolution

When sources disagree on a publication's metadata, priority order:

ORCID (author-curated) > CrossRef (DOI registry, authoritative) > PubMed (NLM-curated) > OpenAlex (algorithmic) > Semantic Scholar (algorithmic) > Google Scholar (scrape).

Record per-field provenance in `source_of_record` dict. Each record might have:

```yaml
source_of_record:
  title: orcid.org
  authors: orcid.org
  doi: crossref.org
  abstract: pubmed
  citation_count: openalex.org
  venue: pubmed
  date: orcid.org
```

## Tiered web acquisition

When fetching external content:

1. **Tier 1 (default):** Bash tool with `curl` or use WebFetch tool. Fast and cheap.
2. **Tier 2 (escalate when Tier 1 fails):** Playwright headless via `mcp__plugin_playwright_playwright__browser_navigate` + `browser_snapshot`.
3. **Tier 3 (escalate when Tier 2 fails):** Spawn real Chrome via Bash with a persistent profile. (Pattern documented in `~/Winnie/CLAUDE.md` browser-scheduled-gap section.)

Record tier used in `source_of_record._tier_used`. Failures at Tier 3 go to `manual_input_flagged` for human-assisted acquisition.

## Output contract

Always return:

```yaml
target: <target>
batch_id: <batch_id>
discovered_records:
  - entity_type: <type>
    fields: {...}
    source_of_record: {field_name: source}
  - ...
next_batch_offset: <int> | null
failures:
  - {target, url_or_query, reason, tier_attempted}
tier_distribution: {tier-1-http: int, tier-2-playwright-headless: int, tier-3-real-chrome: int}
verifications:
  - "PubMed search returned <count> results"
  - "ORCID API returned <count> works"
  - ...
```

The orchestrator passes `discovered_records` to memory-orchestration for persistence.

## Constraints

- Per-source rate limits: PubMed 3 req/sec without API key, 10 with; respect robots.txt; LinkedIn and X scrapes get conservative limits
- Never persist directly; return discovered records to orchestrator
- Per-batch context budget: 200K tokens; if hit, persist what you have via memory-orchestration and signal "incomplete; dispatch continuation"
- Per-batch turn budget: 50 turns
- Apply the inclusion rule strictly

## Tools available

- mcp__claude_ai_PubMed__search_articles, mcp__claude_ai_PubMed__get_article_metadata, mcp__claude_ai_PubMed__find_related_articles
- WebFetch, WebSearch
- mcp__plugin_playwright_playwright__* (full Playwright MCP)
- Bash (yt-dlp, curl, OpenAlex API calls, ORCID API calls, NIH RePORTER queries)
- Read, Write (only to scratch files; persistent state via memory-orchestration)

## Telemetry (heartbeat + per-source + per-batch)

Discovery work involves dozens of external API calls per batch. Emit telemetry at three cadences: per-API-call (real-time source health), heartbeat (every 60s while a batch is in flight), and per-batch summary.

### Per-source `external_call` events (one per API call)

Every external API call emits an `external_call` event with source, status, latency, retry count. Aggregated daily this produces a per-source health dashboard: "PubMed had 5 timeouts today, OpenAlex 200ms median latency, ORCID 1 rate-limit hit."

```bash
~/Winnie/bin/hfo-log --event external_call \
  --skill content-research --correlation-id "<run_id>" \
  --metrics '{"source": "<pubmed|openalex|orcid|crossref|semantic-scholar|google-scholar|listen-notes|news-api|website-crawl>", "endpoint": "<path or URL pattern>", "status_code": <int>, "latency_ms": <int>, "retry_count": <int>, "tier_used": "<tier-1-http|tier-2-playwright-headless|tier-3-real-chrome>", "client_slug": "<slug>", "target": "<discovery target>"}'
```

Volume: dozens to hundreds of these per batch. Acceptable — invocations.jsonl is append-only and the regenerator handles aggregation.

### Heartbeat events (every 60s while batch in flight)

If a batch takes more than 60 seconds, emit `heartbeat` periodically with current activity so the orchestrator (or human monitor) can see progress.

```bash
~/Winnie/bin/hfo-log --event heartbeat \
  --skill content-research --correlation-id "<run_id>" \
  --metrics '{"current_activity": "<one-line: querying OpenAlex page=3 of ~12>", "batch_id": "<batch_id>", "records_so_far": <int>, "elapsed_seconds": <int>}'
```

### Per-batch `skill_completed` event

After each batch dispatch completes, emit a `skill_completed` event via `hfo-log` so the HFO invocation ledger tracks adoption, reliability, tier-escalation patterns, and per-source effectiveness.

```bash
~/Winnie/bin/hfo-log \
  --event skill_completed \
  --skill content-research \
  --department research \
  --entity ccg \
  --status <ok|partial|failed> \
  --correlation-id "<run_id>" \
  --metrics '{"client_slug": "<slug>", "target": "<target>", "batch_id": "<batch_id>", "records_discovered": <int>, "tier_distribution": {"tier-1-http": <int>, "tier-2-playwright-headless": <int>, "tier-3-real-chrome": <int>}, "failures_count": <int>, "duration_s": <float>}'
```

Required even on partial or failed batches: emit with appropriate status and include error class in metrics. Never block real work on telemetry; if `hfo-log` fails, continue.
