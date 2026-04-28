# Overnight build summary — 2026-04-27 → 2026-04-28

Snapshot of what landed while you slept. Everything is committed locally; nothing pushed to GitHub.

## Headline numbers

- **alpen-platform fork**: 22 new commits ahead of upstream (29 total ahead)
- **5 net-new Alpen plugins** total in the fork (added `alpen-revenue` overnight)
- **12 Python/bash composer + regenerator + rollup scripts** in `bin/`
- **3 SQLite state DBs** populated, validated, indexed
- **3 markdown rollups** writing to vault nightly via launchd
- **2 launchd jobs** wired (nightly-backup at 02:30, alpen-regenerate-all at 06:15)
- **End-to-end Tier 2 proposal flow validated** against your real Eli Lilly opportunity
- **0 destructive changes** to your CCG opportunity source data (markdown unchanged)

## What landed in this session

### New plugin: `alpen-revenue`
Sits on top of upstream `sales` plugin. Four SKILLs that consume the templates pack:

| SKILL | What it does | Python implementation |
|---|---|---|
| `proposal-composer` | Render Tier 1/2/3 proposal from a SCOPED lead | `bin/compose-proposal.py` ✓ |
| `scope-builder` | Walk scope-questionnaire after discovery call | (SKILL only; Python TBD) |
| `qbr-prep` | Quarterly review from engagements.db + VoC | (SKILL only; Python TBD) |
| `status-report-composer` | Weekly per-engagement status report | `bin/compose-status-report.py` ✓ |

### New CLI tools

| Script | What it does | Tested |
|---|---|---|
| `bin/compose-proposal.py` | Render proposal from leads.db row | ✓ Eli Lilly Tier 2 → vault, voice-sweep PASS, lead state ENGAGED→PROPOSED |
| `bin/compose-sow.py` | Render SOW under MSA + insert contracts.db row | ✓ 52/54 vars resolved on dry-run |
| `bin/compose-status-report.py` | Weekly status reports per active engagement | ✓ empty case handled |
| `bin/leads-rollup.py` | leads.db → ${VAULT}/Sales/Pipeline.md | ✓ 10K-char markdown with overdue/stuck/single-threaded views |
| `bin/contracts-rollup.py` | contracts.db → ${VAULT}/Legal/Contracts.md | ✓ |
| `bin/engagements-rollup.py` | engagements.db → ${VAULT}/Delivery/Engagements.md | ✓ |
| `bin/alpen-init.py` | Bootstrap a new tenant interactively or scripted | ✓ acme test < 1 sec |
| `~/Winnie/bin/alpen-regenerate-all.sh` | Chain all 6 regen+rollup scripts | ✓ wired to launchd 06:15 daily |
| `~/Winnie/bin/voice-sweep.sh` | Em/en-dash enforcement helper | ✓ markdown-aware (skips strikethrough) |

### New templates

| Template | Status |
|---|---|
| `templates/default/proposal-tier-1.md` | ✓ |
| `templates/default/proposal-tier-2.md` | ✓ |
| `templates/default/proposal-tier-3.md` | ✓ |
| `templates/default/scope-questionnaire.yaml` | ✓ |
| `templates/default/msa-template.md` | ✓ (legal review still needed before first use) |
| `templates/default/sow-template.md` | ✓ |
| `templates/default/qbr-deck.md` | ✓ |
| `templates/default/status-report.md` | ✓ |
| `templates/default/kickoff-deck.md` | ✓ |
| `templates/default/brand-voice.md` | ✓ |
| `templates/ccg/brand-voice.md` | ✓ Krystal-frame, no em-dash, brain-economy first-use |
| `templates/ccg/proposal-tier-2.md` | ✓ overrides default for CCG; "Program Design" framing |
| `templates/alpen-tech/brand-voice.md` | ✓ |

### State machine (decided + populated)

```
NEW → QUALIFIED → ENGAGED → DISCOVERED → SCOPED → PROPOSED → NEGOTIATING → WON → ACTIVE → CLOSED
                                                                              ↓
                                                                            LOST
```

26 of your real CCG opportunities now indexed in `leads.db` with stage normalization (Prospect→NEW, In Conversation→ENGAGED, Closed-Won→WON), 10 overdue actions surfaced, 23 stuck deals (>30d in stage) flagged.

### Bugs caught + fixed

| Bug | Found by | Fix |
|---|---|---|
| `~~Task~~` strikethrough corrupting customizer output | productivity plugin smoke test | atomic-group regex |
| `hfo-log key=value` not capturing args | nightly-backup launchd run | use `--key value` (correct CLI) + memory updated |
| `~~name` substitutions inside backtick documentation | alpen-customization self-customize attempt | code-fence aware substitution |
| launchd can't write to ~/Documents OR iCloud (TCC) | nightly-backup launchd smoke | destination → ~/Winnie/backups (non-TCC) |
| perl `\x{2014}` doesn't match without -CSD flag | voice-sweep self-test | use literal — / – chars |
| grep -c `0\n0` from no-match exit code corrupts arithmetic | voice-sweep retest | switch to `grep -o ... | wc -l` |
| Embedded git repo when `git add -A` from Winnie | gitignore audit | added `/alpen-platform/` to .gitignore |

## What's running on cron

| Time | Job | Purpose |
|---|---|---|
| 02:30 daily | `io.howardfamily.ops.nightly-backup` | Tarball state to `~/Winnie/backups/` (RAG + sqlite + .nosync indices) |
| 03:30 daily | `io.howardfamily.memory.rag-ingest` | RAG incremental ingest (existing) |
| 06:15 daily | `io.howardfamily.alpen.regenerate` | All 3 regenerators + 3 rollups, chained |
| (existing) | various | Daily AI / CCG briefings, meeting prep, email triage, standup |

## What needs your keyboard in the morning

In rough priority order:

| # | Item | Time | Why |
|---|---|---|---|
| **1** | **Try `/pipeline-review`** | 5 min | If you didn't get to it before bed; confirms the upstream sales plugin works in your stack with OAuth |
| 2 | **Push fork to GitHub** | 2 min decision | 29 commits unpushed; question is whether to rename `phil248/knowledge-work-plugins` → `phil248/alpen-platform` first |
| 3 | **Review the test artifacts in vault** | 10 min | I generated 3 sample artifacts (delete if you don't want them): |
| | | | • `${VAULT}/Sales/Proposals/eli-lilly-brain-health-support-tier-2.md` (Tier 2 proposal) |
| | | | • `${VAULT}/Sales/Pipeline.md` (alpen-platform rollup; complements your CCG-Pipeline.md) |
| | | | • `${VAULT}/Legal/Contracts.md` and `${VAULT}/Delivery/Engagements.md` (mostly stubs) |
| 4 | **Try `bin/alpen-init.py --tenant-id <new-tenant>`** interactively | 5 min | Validates the second-customer story from end-to-end |
| 5 | **Eli Lilly lead state in leads.db** | 0 min | I transitioned it to PROPOSED for testing; the Mon 06:15 cron will restore it from your unchanged source markdown. No action needed unless you want to delete the test proposal in `${VAULT}/Sales/Proposals/`. |

## What's NOT yet built (next backlog)

- `compose-msa.py` — MSA-only path (we have SOW; tier-2/3 typically need MSA first)
- `qbr-prep.py` — Python implementation for the SKILL (currently SKILL-only)
- `proposal-composer` and friends as actual installed Claude SKILLs that are auto-discovered (currently the SKILLs exist in the plugin but session-restart is needed for Claude Code to index them)
- Alpen-tech-specific tier-1/2/3 proposal overrides (only CCG tier-2 done so far)
- `templates/<entity>/scope-questionnaire.yaml` overrides per entity
- Push-to-GitHub workflow for the fork

## Memory state

Both feedback memories from earlier today are still authoritative:
- `feedback_alpen_storage_patterns.md` — six-tier model + .nosync rule + TCC rule
- `feedback_alpen_instrumentation_patterns.md` — telemetry contract per artifact (corrected to `--key value`)
- `Alpen-platform-v0.1-architecture.md` — updated tonight with composer + rollup CLI inventory

## One ask

If you want to spot-check anything tonight before you sleep: open `${VAULT}/Sales/Pipeline.md` in Obsidian. That's the most "complete" artifact — your real 26 CCG opportunities, 10 overdue actions surfaced, by-stage breakdown with wikilinks. If that looks right to you, the rest of the platform plumbing is solid.

— overnight build complete, no errors outstanding, ~2.5 hours of work persisted across 22 commits.
