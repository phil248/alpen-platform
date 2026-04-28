# Schemas

SQLite DDL for the Alpen Platform state-machine spine.

## The opportunity-flow state machine

```
                                                                 ┌──────► LOST
                                                                 │
NEW → QUALIFIED → ENGAGED → DISCOVERED → SCOPED → PROPOSED → NEGOTIATING ──► WON ──► (handoff to engagements.db)
                                                                                            │
                                                                                            ▼
                                                                                          ACTIVE ──► CHANGE_ORDER (in-place loop)
                                                                                            │
                                                                                            ▼
                                                                                          CLOSED
                                                                                            │
                                                                                            ▼
                                                                                  (handoff back to leads.db
                                                                                   for expansion as new lead)
```

Three databases hold the state:

| DB | What it tracks | Lives at |
|---|---|---|
| `leads.db` | Pre-contract opportunity flow (NEW → WON/LOST) | `~/.local/state/alpen/sqlite/leads.db` |
| `contracts.db` | Contract lifecycle (DRAFT → EXECUTED → AMENDED → TERMINATED) | `~/.local/state/alpen/sqlite/contracts.db` |
| `engagements.db` | Active delivery (NEW → ACTIVE → CHANGE_ORDER → CLOSED) | `~/.local/state/alpen/sqlite/engagements.db` |

Per `feedback_alpen_storage_patterns.md`:
- Single writer per DB (typically Mac mini)
- Markdown is truth (per-record .md files in vault); SQLite is regenerable index
- Never on iCloud / Google Drive
- Backed up nightly via `~/Winnie/bin/nightly-backup.sh`

## Markdown source of truth

Each row in each DB has a corresponding markdown file:

| Table | Markdown source |
|---|---|
| `leads.db.lead` | `${VAULT}/Sales/Leads/<slug>.md` (or per-tenant equivalent) |
| `leads.db.lead_history` | the lead's `## History` section (append-only) |
| `contracts.db.contract` | `${VAULT}/Legal/Contracts/<slug>.md` |
| `engagements.db.engagement` | `${VAULT}/Delivery/Engagements/<slug>.md` |

CCG already runs this exact pattern for opportunities (`Cognitive-Capital-Group/Opportunities/<slug>.md` regenerated into `.opportunities.db.nosync` by `~/Winnie/bin/regenerate-pipeline-rollup.py`). The platform-level schemas generalize that approach.

## Foreign keys are LOOSE

Cross-DB references (e.g., `engagement.contract_id` in engagements.db pointing to contracts.db) are stored as TEXT slugs, not enforced FOREIGN KEY relationships. Three reasons:

1. SQLite cannot enforce foreign keys across separate database files
2. Each DB can be regenerated independently from its markdown source
3. Cross-DB joins use ATTACH DATABASE in queries that need them

See `schemas/sql/joins-attach-example.sql` for the join pattern.

## Migration

Per the storage-patterns memory, migrations are markdown edits, not direct SQL. To add a new field:

1. Update the per-record markdown frontmatter convention
2. Update the regenerator script to extract the new field
3. Drop and rebuild the SQLite from markdown

Never `ALTER TABLE` on a live DB; let the rebuild handle it.
