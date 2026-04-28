-- engagements.db — active delivery (NEW → ACTIVE → CHANGE_ORDER (loop) → CLOSED)
-- Source of truth: ${VAULT}/Delivery/Engagements/<slug>.md per tenant
-- Per feedback_alpen_storage_patterns.md: regenerable from markdown.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

-- ─── Core engagement ───
CREATE TABLE IF NOT EXISTS engagement (
  id                TEXT PRIMARY KEY,              -- slug (e.g. "acme-pharma-2026q2")
  tenant_id         TEXT NOT NULL,
  entity_id         TEXT NOT NULL,                 -- ccg | alpen-tech
  display_name      TEXT NOT NULL,
  client_name       TEXT NOT NULL,
  tier              INTEGER NOT NULL,              -- 1 | 2 | 3
  status            TEXT NOT NULL,                 -- see CHECK below
  health_score      INTEGER,                       -- 0-100; NULL until first scoring
  health_color      TEXT,                          -- "green" | "yellow" | "red"
  -- timing
  kickoff_date      DATE,
  planned_end_date  DATE,
  actual_end_date   DATE,
  -- people
  principal_owner   TEXT NOT NULL,                 -- phil | krystal
  client_poc_name   TEXT,
  client_poc_email  TEXT,
  client_sponsor_name TEXT,
  -- commercials
  contract_id       TEXT NOT NULL,                 -- contracts.db.contract.id (the SOW)
  msa_contract_id   TEXT,                          -- contracts.db.contract.id (the parent MSA)
  total_value       INTEGER,                       -- USD
  hours_budget      REAL,                          -- if hour-budgeted
  -- vault
  vault_path        TEXT NOT NULL,
  -- timestamps
  created_at        DATETIME NOT NULL DEFAULT (datetime('now')),
  updated_at        DATETIME NOT NULL DEFAULT (datetime('now')),
  CHECK (tier IN (1, 2, 3)),
  CHECK (status IN ('NEW', 'KICKOFF', 'ACTIVE', 'AT_RISK', 'PAUSED', 'CLOSED', 'CANCELLED')),
  CHECK (health_color IS NULL OR health_color IN ('green', 'yellow', 'red')),
  CHECK (health_score IS NULL OR (health_score >= 0 AND health_score <= 100)),
  CHECK (actual_end_date IS NULL OR status IN ('CLOSED', 'CANCELLED'))
);

CREATE INDEX IF NOT EXISTS idx_engagement_status ON engagement(status);
CREATE INDEX IF NOT EXISTS idx_engagement_owner_status ON engagement(principal_owner, status);
CREATE INDEX IF NOT EXISTS idx_engagement_health ON engagement(health_color, status);
CREATE INDEX IF NOT EXISTS idx_engagement_planned_end ON engagement(planned_end_date) WHERE planned_end_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_engagement_contract ON engagement(contract_id);

-- ─── Deliverables (1:N from engagement) ───
CREATE TABLE IF NOT EXISTS engagement_deliverable (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  engagement_id     TEXT NOT NULL,
  sequence          INTEGER NOT NULL,              -- 1, 2, 3...
  name              TEXT NOT NULL,
  description       TEXT,
  acceptance_criteria TEXT,
  due_date          DATE,
  delivered_at      DATETIME,
  accepted_at       DATETIME,
  rejected_at       DATETIME,
  rejection_reason  TEXT,
  status            TEXT NOT NULL DEFAULT 'PLANNED',
  vault_path        TEXT,                          -- per-deliverable file in engagement folder
  CHECK (status IN ('PLANNED', 'IN_PROGRESS', 'DELIVERED', 'ACCEPTED', 'REJECTED')),
  FOREIGN KEY (engagement_id) REFERENCES engagement(id) ON DELETE CASCADE,
  UNIQUE (engagement_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_deliverable_engagement ON engagement_deliverable(engagement_id);
CREATE INDEX IF NOT EXISTS idx_deliverable_status ON engagement_deliverable(status);
CREATE INDEX IF NOT EXISTS idx_deliverable_due ON engagement_deliverable(due_date) WHERE due_date IS NOT NULL;

-- ─── Change orders (in-place state-machine loops) ───
CREATE TABLE IF NOT EXISTS engagement_change_order (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  engagement_id     TEXT NOT NULL,
  change_order_number INTEGER NOT NULL,            -- 1, 2, 3...
  description       TEXT NOT NULL,
  scope_delta       TEXT,                          -- "added integration with FactSet"
  value_delta       INTEGER,                       -- USD; can be negative
  hours_delta       REAL,                          -- can be negative
  schedule_delta_days INTEGER,                     -- can be negative
  proposed_at       DATETIME,
  approved_at       DATETIME,
  rejected_at       DATETIME,
  status            TEXT NOT NULL DEFAULT 'PROPOSED',
  contract_amendment_id INTEGER,                   -- contracts.db.contract_amendment.id (loose ref)
  vault_path        TEXT,
  CHECK (status IN ('PROPOSED', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'WITHDRAWN')),
  FOREIGN KEY (engagement_id) REFERENCES engagement(id) ON DELETE CASCADE,
  UNIQUE (engagement_id, change_order_number)
);

CREATE INDEX IF NOT EXISTS idx_change_order_engagement ON engagement_change_order(engagement_id);
CREATE INDEX IF NOT EXISTS idx_change_order_status ON engagement_change_order(status);

-- ─── Status reports (1:N from engagement; weekly) ───
CREATE TABLE IF NOT EXISTS engagement_status_report (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  engagement_id     TEXT NOT NULL,
  week_start_date   DATE NOT NULL,
  health_score      INTEGER,
  health_color      TEXT,
  hours_used_week   REAL,
  hours_used_total  REAL,
  budget_status     TEXT,                          -- "on_track" | "at_risk" | "over"
  tldr              TEXT,
  vault_path        TEXT NOT NULL,                 -- per-week status report file
  generated_at      DATETIME NOT NULL DEFAULT (datetime('now')),
  CHECK (health_color IS NULL OR health_color IN ('green', 'yellow', 'red')),
  CHECK (budget_status IS NULL OR budget_status IN ('on_track', 'at_risk', 'over')),
  FOREIGN KEY (engagement_id) REFERENCES engagement(id) ON DELETE CASCADE,
  UNIQUE (engagement_id, week_start_date)
);

CREATE INDEX IF NOT EXISTS idx_status_engagement_week ON engagement_status_report(engagement_id, week_start_date DESC);

-- ─── Risks (per engagement; tracked over time) ───
CREATE TABLE IF NOT EXISTS engagement_risk (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  engagement_id     TEXT NOT NULL,
  identified_at     DATETIME NOT NULL DEFAULT (datetime('now')),
  description       TEXT NOT NULL,
  severity          TEXT NOT NULL,                 -- "low" | "medium" | "high" | "critical"
  owner             TEXT,
  mitigation        TEXT,
  status            TEXT NOT NULL DEFAULT 'OPEN',
  resolved_at       DATETIME,
  CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  CHECK (status IN ('OPEN', 'MITIGATED', 'CLOSED', 'MATERIALIZED')),
  FOREIGN KEY (engagement_id) REFERENCES engagement(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_risk_engagement_status ON engagement_risk(engagement_id, status);
CREATE INDEX IF NOT EXISTS idx_risk_severity_open ON engagement_risk(severity, status) WHERE status = 'OPEN';

-- ─── Useful views ───

-- Active engagements with health
CREATE VIEW IF NOT EXISTS v_active_engagements AS
SELECT
  e.id, e.display_name, e.client_name, e.tier, e.principal_owner,
  e.status, e.health_score, e.health_color,
  e.planned_end_date,
  CASE
    WHEN e.planned_end_date IS NULL THEN NULL
    ELSE julianday(e.planned_end_date) - julianday('now')
  END AS days_remaining,
  e.total_value
FROM engagement e
WHERE e.status IN ('ACTIVE', 'AT_RISK', 'KICKOFF')
ORDER BY
  CASE e.health_color WHEN 'red' THEN 1 WHEN 'yellow' THEN 2 ELSE 3 END,
  e.planned_end_date NULLS LAST;

-- Engagements at risk (red or yellow health)
CREATE VIEW IF NOT EXISTS v_at_risk_engagements AS
SELECT
  e.id, e.display_name, e.client_name, e.health_score, e.health_color,
  COUNT(r.id) AS open_risks
FROM engagement e
LEFT JOIN engagement_risk r ON r.engagement_id = e.id AND r.status = 'OPEN'
WHERE e.status IN ('ACTIVE', 'AT_RISK')
  AND (e.health_color IN ('yellow', 'red') OR e.status = 'AT_RISK')
GROUP BY e.id
ORDER BY
  CASE e.health_color WHEN 'red' THEN 1 WHEN 'yellow' THEN 2 ELSE 3 END,
  open_risks DESC;

-- Deliverables due in next 14 days
CREATE VIEW IF NOT EXISTS v_deliverables_upcoming AS
SELECT
  d.id, d.engagement_id, e.display_name AS engagement_name,
  d.name AS deliverable_name, d.due_date,
  julianday(d.due_date) - julianday('now') AS days_to_due
FROM engagement_deliverable d
JOIN engagement e ON e.id = d.engagement_id
WHERE d.status NOT IN ('DELIVERED', 'ACCEPTED', 'REJECTED')
  AND d.due_date IS NOT NULL
  AND julianday(d.due_date) - julianday('now') BETWEEN 0 AND 14
ORDER BY d.due_date;

-- Engagements that haven't had a status report in 10+ days (process risk)
CREATE VIEW IF NOT EXISTS v_status_report_overdue AS
SELECT
  e.id, e.display_name, e.client_name,
  MAX(s.week_start_date) AS last_status_date,
  julianday('now') - julianday(MAX(s.week_start_date)) AS days_since_last
FROM engagement e
LEFT JOIN engagement_status_report s ON s.engagement_id = e.id
WHERE e.status IN ('ACTIVE', 'AT_RISK')
GROUP BY e.id
HAVING days_since_last > 10 OR last_status_date IS NULL;
