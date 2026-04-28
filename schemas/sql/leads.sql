-- leads.db — pre-contract opportunity flow
-- Source of truth: ${VAULT}/Sales/Leads/<slug>.md per tenant
-- Per feedback_alpen_storage_patterns.md: regenerable from markdown.
-- DO NOT ALTER directly; rebuild from source via bin/regenerate-leads-index.py

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;  -- enforced within this DB; cross-DB refs are TEXT

-- ─── Core lead record ───
CREATE TABLE IF NOT EXISTS lead (
  id              TEXT PRIMARY KEY,                -- slug, lowercase, kebab-case (e.g. "acme-pharma-2026q2")
  tenant_id       TEXT NOT NULL,                   -- which tenant owns this lead
  entity_id       TEXT NOT NULL,                   -- ccg | alpen-tech | etc.
  display_name    TEXT NOT NULL,                   -- "Acme Pharma — AI Ops Platform Tier 2"
  company_name    TEXT,
  primary_contact TEXT,                            -- "Sarah Chen, VP Engineering"
  contact_email   TEXT,
  source          TEXT NOT NULL,                   -- referral | inbound | event | outbound | warm-intro
  source_detail   TEXT,                            -- "referred by krystal" | "G7 Houston event"
  stage           TEXT NOT NULL,                   -- see lead_stage CHECK below
  tier            INTEGER,                         -- 1 | 2 | 3 (or NULL pre-scoping)
  value_estimate  INTEGER,                         -- USD; NULL when unknown
  value_low       INTEGER,                         -- range bound when uncertain
  value_high      INTEGER,
  probability     REAL,                            -- 0.0 to 1.0; informs weighted pipeline
  owner           TEXT NOT NULL,                   -- principal id (phil | krystal)
  next_action     TEXT,
  next_action_due DATE,
  next_action_owner TEXT,
  stage_entered_date  DATE NOT NULL,               -- per HFO opportunity-review pattern; enables stuck detection
  created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
  updated_at      DATETIME NOT NULL DEFAULT (datetime('now')),
  closed_at       DATETIME,                        -- set on WON or LOST
  close_reason    TEXT,                            -- on WON: how / why won; on LOST: why
  -- references to other DBs (loose; cross-DB FK not enforceable in SQLite)
  contract_id     TEXT,                            -- contracts.db.contract.id when WON and contract drafted
  engagement_id   TEXT,                            -- engagements.db.engagement.id when WON and engagement spawned
  vault_path      TEXT NOT NULL,                   -- relative path to source markdown file
  CHECK (stage IN (
    'NEW', 'QUALIFIED', 'ENGAGED', 'DISCOVERED', 'SCOPED',
    'PROPOSED', 'NEGOTIATING', 'WON', 'LOST', 'DISQUALIFIED'
  )),
  CHECK (tier IS NULL OR tier IN (1, 2, 3)),
  CHECK (probability IS NULL OR (probability >= 0.0 AND probability <= 1.0)),
  CHECK (closed_at IS NULL OR stage IN ('WON', 'LOST', 'DISQUALIFIED'))
);

CREATE INDEX IF NOT EXISTS idx_lead_stage ON lead(stage);
CREATE INDEX IF NOT EXISTS idx_lead_owner_stage ON lead(owner, stage);
CREATE INDEX IF NOT EXISTS idx_lead_due ON lead(next_action_due) WHERE next_action_due IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lead_stuck ON lead(stage, stage_entered_date);
CREATE INDEX IF NOT EXISTS idx_lead_value ON lead(value_estimate) WHERE value_estimate IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lead_entity_stage ON lead(entity_id, stage);

-- ─── Lead history (append-only) ───
-- Mirrors the per-opp markdown ## History section. One row per recorded change.
CREATE TABLE IF NOT EXISTS lead_history (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id         TEXT NOT NULL,
  occurred_at     DATETIME NOT NULL,               -- when the change happened (not when ingested)
  source          TEXT,                            -- "plaud-breckenridge-2026-03-29" | "manual" | "email-thread"
  event_type      TEXT NOT NULL,                   -- stage_change | next_action_set | value_updated | note
  from_stage      TEXT,                            -- on stage_change: previous stage
  to_stage        TEXT,                            -- on stage_change: new stage
  description     TEXT NOT NULL,                   -- human-readable summary (one line)
  body            TEXT,                            -- optional longer note
  ingested_at     DATETIME NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (lead_id) REFERENCES lead(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lead_history_lead ON lead_history(lead_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_lead_history_event ON lead_history(event_type, occurred_at DESC);

-- ─── Lead contacts (multi-stakeholder support) ───
CREATE TABLE IF NOT EXISTS lead_contact (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id         TEXT NOT NULL,
  name            TEXT NOT NULL,
  title           TEXT,
  email           TEXT,
  role            TEXT,                            -- decision-maker | champion | influencer | blocker | technical-evaluator
  notes           TEXT,
  added_at        DATETIME NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (lead_id) REFERENCES lead(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lead_contact_lead ON lead_contact(lead_id);
CREATE INDEX IF NOT EXISTS idx_lead_contact_role ON lead_contact(role);

-- ─── Useful views ───

-- Pipeline by stage with weighted-value rollup
CREATE VIEW IF NOT EXISTS v_pipeline_summary AS
SELECT
  entity_id,
  stage,
  COUNT(*) as deal_count,
  SUM(COALESCE(value_estimate, (value_low + value_high) / 2, 0)) as raw_value,
  SUM(COALESCE(value_estimate, (value_low + value_high) / 2, 0) * COALESCE(probability, 0.0)) as weighted_value
FROM lead
WHERE stage NOT IN ('WON', 'LOST', 'DISQUALIFIED')
GROUP BY entity_id, stage;

-- Stuck deals (in same stage > 30 days)
CREATE VIEW IF NOT EXISTS v_stuck_deals AS
SELECT
  id, display_name, owner, stage, value_estimate,
  julianday('now') - julianday(stage_entered_date) AS days_stuck
FROM lead
WHERE stage NOT IN ('WON', 'LOST', 'DISQUALIFIED')
  AND julianday('now') - julianday(stage_entered_date) > 30
ORDER BY days_stuck DESC;

-- Overdue actions
CREATE VIEW IF NOT EXISTS v_overdue_actions AS
SELECT
  id, display_name, owner, stage, next_action, next_action_due,
  julianday('now') - julianday(next_action_due) AS days_overdue
FROM lead
WHERE next_action_due IS NOT NULL
  AND next_action_due < date('now')
  AND stage NOT IN ('WON', 'LOST', 'DISQUALIFIED')
ORDER BY days_overdue DESC;

-- Single-threaded deals (single contact)
CREATE VIEW IF NOT EXISTS v_single_threaded AS
SELECT
  l.id, l.display_name, l.owner, l.stage, l.value_estimate,
  COUNT(c.id) AS contact_count
FROM lead l
LEFT JOIN lead_contact c ON c.lead_id = l.id
WHERE l.stage NOT IN ('WON', 'LOST', 'DISQUALIFIED')
GROUP BY l.id
HAVING contact_count <= 1
ORDER BY l.value_estimate DESC NULLS LAST;
