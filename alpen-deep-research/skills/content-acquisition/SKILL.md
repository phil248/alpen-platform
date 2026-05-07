---
name: content-acquisition
description: >
  USE THIS SKILL whenever you need to download and cache binary content
  (PDFs, audio, video, decks, images) from URLs into the per-client vault
  _assets/ folder, snapshot to web.archive.org, with tiered escalation
  (curl/wget/yt-dlp -> Playwright headless -> real Chrome) when fetch
  fails. Trigger phrases include: 'download these PDFs', 'cache the
  content', 'fetch the binary assets', 'snapshot these URLs', 'download
  papers from these links', 'archive these URLs', 'acquire this content',
  'pull these files into _assets', 'wayback these URLs', 'save these
  PDFs to disk', 'fetch the deck', 'grab the audio file'. Common in
  client-content-inventory work for CCG, Center for BrainHealth, Alpen
  Tech, Krystal speaking research. CRITICAL: every claim of download
  must be backed by an actual file on disk; never fabricate downloads.
  Always use this skill when binary content needs to be pulled from URLs
  — do NOT pick content-processing (that converts already-cached binaries
  to text) or content-research (that discovers URLs).
---

# content-acquisition

## CRITICAL RULES (NON-NEGOTIABLE)

1. **Every claim of download MUST be backed by an actual file on disk WITH FORMAT-CORRECT MAGIC BYTES.** (tightened 2026-05-07; audit finding #8). After every download attempt, verify the file exists at the expected path with non-zero bytes AND verify its magic bytes match the declared format. For PDFs: `file '<path>' | grep -q 'PDF document'` OR `head -c 4 '<path>' | grep -q '^%PDF'`. On 2026-05-07 audit, 8 of 10 "downloaded" PDFs in Phase A were actually HTML login pages renamed `.pdf` — content-acquisition never magic-byte-checked, downstream content-processing then tried to extract text and silently produced garbage. If magic bytes do not match: set `download_status: failed-content-mismatch`, write the html-as-pdf to `_assets/html/<slug>.html` for downstream HTML extraction, and re-attempt the original target at Tier 2. Never declare a PDF download successful when the file is HTML.

2. **Use real fetch tools.** HTTP downloads MUST use Bash with `curl` or `wget` (or `yt-dlp` for audio/video). Tier 2 escalation MUST use `mcp__plugin_playwright_playwright__browser_navigate` plus `browser_snapshot`. Do not narrate downloads.

3. **Atomic downloads.** Download to `<final_path>.tmp` first; only `mv` to the final path if the download succeeds and produces non-zero bytes. Never leave partial files at the final path.

4. **Record the actual tier used.** If you tried Tier 1 and failed, then succeeded with Tier 2, set `tier_used: tier-2-playwright-headless`. Do not claim Tier 1 success when you escalated.

5. **Mark paywalls and auth blocks honestly.** When a download fails because of a paywall or authentication, set `download_status: blocked-by-paywall` or `blocked-by-auth` with explanation in `notes`. Do not retry indefinitely; flag for manual_input.

6. **web.archive.org snapshots are part of every URL.** Even if download fails, request a Wayback Machine snapshot via Bash curl POST to `https://web.archive.org/save/<url>`. Record the resulting `archive_url` in the ContentAsset.

## Purpose

For each URL in the input batch:
1. Fetch the binary content
2. Cache it locally in `<vault_root>/_assets/<format>/`
3. Snapshot the URL to web.archive.org
4. Return a ContentAsset record with `local_path` populated (or `download_status: failed` with explicit reason)

## Tiered escalation

For each URL:

### Tier 1: HTTP fetch via Bash

```bash
# For documents/images:
curl -L -o '<vault_root>/_assets/<format>/<slug>.<ext>.tmp' '<url>'
# Magic-byte validator BEFORE the mv (added 2026-05-07; audit finding #8):
if [[ "<format>" == "pdf" ]]; then
  if ! file '<vault_root>/_assets/<format>/<slug>.<ext>.tmp' | grep -q 'PDF document'; then
    # Not a real PDF — preserve as html-as-pdf for downstream HTML extraction,
    # mark download_status=failed-content-mismatch, escalate to Tier 2.
    mv '<vault_root>/_assets/<format>/<slug>.<ext>.tmp' '<vault_root>/_assets/html/<slug>.html'
    echo 'PDF magic bytes missing; preserved as HTML; escalating to Tier 2'
    # ... Tier 2 retry path here
  fi
fi
mv '<vault_root>/_assets/<format>/<slug>.<ext>.tmp' '<vault_root>/_assets/<format>/<slug>.<ext>'

# OA fallback (added 2026-05-07; audit finding #7): if the primary url returns
# paywalled or blocked-by-auth content AND the parent publication record has a
# non-empty `secondary_urls` (populated upstream from OpenAlex open_access.oa_url),
# automatically retry against secondary_urls[0] before declaring blocked-by-paywall.
# OpenAlex OA mirrors recovered 17 PDFs missed by Phase 1 publisher URLs.

# For audio/video:
/opt/homebrew/bin/yt-dlp -o '<vault_root>/_assets/audio/<slug>.%(ext)s' '<url>'
```

After: verify with `ls -la` and `stat`. If body size is suspiciously small (<1KB for content URLs), escalate to Tier 2.

### Tier 2: real Chrome via CDP (DISPATCH TO SCRIPT)

**DO NOT replicate this protocol inline.** Tier 2 escalation is a single Python call:

```python
from lib.content_acquisition.tier2_playwright import fetch_pdf_tier2
result = fetch_pdf_tier2(url, output_path)
# result keys: status (ok|failed-content-mismatch|failed-network|failed-paywall),
#              magic_bytes_pdf, bytes_downloaded, final_url, error
```

Or via Bash:

```bash
~/Winnie/rag/venv/bin/python -m lib.content_acquisition.tier2_playwright \
  --url '<url>' --output '<vault_root>/_assets/pdfs/<slug>.pdf'
```

The script connects to the persistent `winnie-chrome` daemon at `http://localhost:9222` (CDP), navigates, waits for network idle + 5s for Cloudflare, attempts direct PDF body capture, falls back to publisher "Download PDF" button click, magic-byte validates with `file(1)` + raw `%PDF` header check, and atomically promotes `.tmp` to the final path. Set `tier_used: tier-2-playwright-headless` only when the dispatch returns `status: ok`.

**Setup requirement (one-time):** `~/Winnie/rag/venv/bin/pip install playwright`. The browser binary is NOT needed — winnie-chrome is the browser, we just attach via CDP. No `playwright install` needed.

If the script returns `failed-content-mismatch` (HTML rendered as PDF), preserve the body to `_assets/html/<slug>.html` for downstream HTML extraction and continue to Tier 3. If `failed-paywall`, skip Tier 3 and mark `blocked-by-paywall`. Do NOT call the raw Playwright MCP from inside the agent — the script is the protocol.

### Tier 3: Real Chrome with persistent profile

For sites that block headless browsers (LinkedIn, X, some publishers):

```bash
# Launch Chrome with persistent profile (per ~/Winnie/CLAUDE.md browser-scheduled-gap pattern)
open -a 'Google Chrome' --args --user-data-dir=/Users/philhoward/Library/Application\ Support/Client-Inventories/_chrome-profiles/<client_slug> '<url>'
# Wait for download; check ~/Downloads or specified path
```

### Manual fallback

If Tier 3 fails or the URL requires interactive captcha, mark `download_status: blocked-by-auth`, add to `manual_input_flagged` list with explanatory note. Phil or Krystal manually handles these later.

## Storage layout

Cached files go to per-format subdirectories under `<vault_root>/_assets/`:
- PDFs: `_assets/pdfs/<slug>.pdf`
- Audio: `_assets/audio/<slug>.mp3`
- Video: `_assets/video/<slug>.mp4`
- Decks: `_assets/decks/<slug>.pptx`
- Images: `_assets/images/<slug>.<ext>`
- Other: `_assets/other/<slug>.<ext>`

Filename slug rules: deterministic from canonical_url SHA-256 (first 16 hex chars) or DOI-based. Lowercase, hyphenated.

## License status detection

Set `license_status` for each acquired asset. Detection logic:

- If URL contains `pmc.ncbi.nlm.nih.gov`, `arxiv.org`, `biorxiv.org`, `plos.org`: `open-access`
- If URL is a Creative Commons-licensed page: `cc-licensed`
- If URL is `uspto.gov` or `patents.google.com`: `public-domain`
- If first attempt returns 401/403 with paywall headers: `paywalled` (then attempt Unpaywall)
- Else: `unclear`

For paywalled academic publications, attempt Unpaywall lookup:

```bash
curl 'https://api.unpaywall.org/v2/<doi>?email=phil@cognitivecapitalgroup.com'
```

If Unpaywall returns an OA mirror URL, retry the download from the OA source and update `license_status: open-access`.

## web.archive.org snapshots

For every URL processed, request a snapshot:

```bash
curl -X POST 'https://web.archive.org/save/<url>' -I 2>&1 | grep -i location
```

Parse the `Location:` header for the resulting archive URL. Record in ContentAsset's `archive_url` field. If the snapshot request fails, record `archive_url: null` with a note.

## Output contract

```yaml
batch_id: <batch_id>
acquired_assets:
  - parent_entity_type: <type>
    parent_entity_id: <slug>
    source_url: <url>
    archive_url: <wayback_url> | null
    format: <format>
    local_path: <vault-relative path>
    file_size_bytes: <int>  # MUST match actual file size
    download_status: completed | blocked-by-paywall | blocked-by-auth | failed
    license_status: <status>
    tier_used: tier-1-http | tier-2-playwright-headless | tier-3-real-chrome | manual
    notes: <free-text>
failed_acquisitions:
  - {url, reason, tier_attempted}
manual_input_flagged: list of urls
tier_distribution: {tier-1-http: int, tier-2-playwright-headless: int, tier-3-real-chrome: int, manual: int}
verifications:
  - "ls -la output for each acquired asset showing actual byte count"
```

## Constraints

- Per-batch context budget: 100K tokens
- Per-batch turn budget: 50 turns
- Default batch size: 50 URLs
- Same external host never hit by parallel acquisition workers (orchestrator sequences API-bound work)
- Always atomic: `.tmp` then `mv`

## Tools available

- Bash with system tools at absolute paths:
  - `/opt/homebrew/bin/yt-dlp` (audio/video URL extraction; verify path with `which yt-dlp` if first call fails)
  - `/opt/homebrew/bin/ffmpeg` (audio extraction from video)
  - `/opt/homebrew/bin/curl` or system `curl` (HTTP fetch)
  - `/opt/homebrew/bin/wget` if available
- WebFetch
- mcp__plugin_playwright_playwright__* (Playwright MCP for Tier 2)
- Real Chrome via Playwright spawn (for Tier 3, per HFO browser-scheduled-gap pattern)
- Read, Write (write to local _assets/ paths)

**Critical environment note:** `claude -p` subprocesses do NOT inherit interactive shell PATH. Tools installed via Homebrew at `/opt/homebrew/bin/` MUST be referenced by absolute path or via `command -v <tool>` lookup. Do NOT assume bare `yt-dlp` will resolve. CBH Phase 1 Stage 6 hit this — yt-dlp was installed but the agent couldn't find it, resulting in 3 YouTube videos saved as HTML page snapshots only.

**PMC PDF retrieval workflow (REQUIRED escalation, not optional):** PMC direct PDF URLs (`ncbi.nlm.nih.gov/pmc/articles/*/pdf/*`) return JavaScript-required HTML viewer pages, not binary PDFs. When you encounter a PMC URL, do NOT attempt direct Tier 1 HTTP fetch. Skip directly to Tier 2 Playwright escalation:

```
mcp__plugin_playwright_playwright__browser_navigate(url="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC<id>/")
mcp__plugin_playwright_playwright__browser_snapshot()
# Locate the PDF download link/button (typically an <a> with text "PDF" or class containing "pdf-download")
# Use browser_evaluate to extract the href, or browser_click + handle download dialog
```

Alternative: register for an EuropePMC API key (free at https://europepmc.org/RestfulWebService) and use the ptpmcrender endpoint with `Authorization: Bearer <key>` header. Without a key, ptpmcrender returns 403.

Real bug: CBH Phase 1 Stage 6 attempted direct Tier 1 fetch on 6 PMC URLs and got HTML viewers; ptpmcrender returned 403 without auth. All 6 articles were unacquired. The fix is to detect PMC URL patterns and skip to Tier 2 immediately.

**PMC URL detection regex:** `r'^https?://(?:www\.)?ncbi\.nlm\.nih\.gov/pmc/articles/PMC\d+'` — match this pattern and route to Tier 2 unconditionally.

**Paywall handling for older corpora:** Sandra Chapman's 2000-2015 papers (~150 of 225) are largely behind Wiley/Elsevier/Sage paywalls. Unpaywall returns ~77% "closed" for this era. This is a structural pre-OA-era issue, not a fetch bug. Document in deliverable; offer UT Dallas institutional access as Phase 2 upgrade.

## Telemetry (per-call + heartbeat + per-batch)

Acquisition is the most external-network-dependent stage. Emit telemetry at three cadences: per-call (real-time host health), heartbeat (per minute while a batch is downloading), and per-batch summary.

### Per-call `external_call` events

Every download attempt emits `external_call` with host, status, latency, tier-used, retry count. Aggregated per host this surfaces "linkedin.com requires Tier 3 90% of the time" and "publisher X always paywalls."

```bash
~/Winnie/bin/hfo-log --event external_call \
  --skill content-acquisition --correlation-id "<run_id>" \
  --metrics '{"source_host": "<extract from URL>", "url": "<full URL>", "status_code": <int>, "latency_ms": <int>, "tier_used": "<tier-1-http|tier-2-playwright-headless|tier-3-real-chrome>", "retry_count": <int>, "bytes_downloaded": <int>, "license_status": "<status>", "client_slug": "<slug>"}'
```

### Per-tier success rates

After every download attempt, also emit a `tier_attempt` event capturing whether the tier succeeded or escalated. Aggregated this answers "is Tier 3 worth its cost? what fraction of URLs need Tier 2 escalation?"

```bash
~/Winnie/bin/hfo-log --event tier_attempt \
  --skill content-acquisition --correlation-id "<run_id>" \
  --metrics '{"tier": "<tier-1-http|tier-2-playwright-headless|tier-3-real-chrome>", "outcome": "<succeeded|escalated|failed>", "url": "<URL>", "source_host": "<host>", "client_slug": "<slug>"}'
```

### Heartbeat events (every 60s while batch in flight)

```bash
~/Winnie/bin/hfo-log --event heartbeat \
  --skill content-acquisition --correlation-id "<run_id>" \
  --metrics '{"current_activity": "<one-line: downloading url 18 of 50, tier=2>", "batch_id": "<batch_id>", "urls_processed_so_far": <int>, "elapsed_seconds": <int>}'
```

### Per-batch `skill_completed` event

After each acquisition batch completes, emit a `skill_completed` event via `hfo-log`. The metrics are especially valuable for tier-escalation analysis (how often does Tier 1 work, how often must we escalate, which sources require Tier 3) and paywall-rate tracking.

```bash
~/Winnie/bin/hfo-log \
  --event skill_completed \
  --skill content-acquisition \
  --department research \
  --entity ccg \
  --status <ok|partial|failed> \
  --correlation-id "<run_id>" \
  --metrics '{"client_slug": "<slug>", "batch_id": "<batch_id>", "urls_attempted": <int>, "urls_succeeded": <int>, "urls_blocked_paywall": <int>, "urls_blocked_auth": <int>, "urls_failed": <int>, "tier_distribution": {"tier-1-http": <int>, "tier-2-playwright-headless": <int>, "tier-3-real-chrome": <int>, "manual": <int>}, "manual_input_flagged_count": <int>, "bytes_downloaded": <int>, "duration_s": <float>}'
```

Required even on partial or failed batches. Never block real work on telemetry; if `hfo-log` fails, continue.
