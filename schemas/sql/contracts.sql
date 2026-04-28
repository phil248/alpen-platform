-- contracts.db — contract lifecycle (DRAFT → EXECUTED → AMENDED → TERMINATED)
-- Source of truth: ${VAULT}/Legal/Contracts/<slug>.md per tenant
-- Per feedback_alpen_storage_patterns.md: regenerable from markdown.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

-- ─── Core contract record ───
CREATE TABLE IF NOT EXISTS contract (
  id                TEXT PRIMARY KEY,              -- slug (e.g. "msa-acme-2026")
  tenant_id         TEXT NOT NULL,
  entity_id         TEXT NOT NULL,
  contract_type     TEXT NOT NULL,                 -- MSA | SOW | NDA | LOI | AMENDMENT | OTHER
  parent_contract_id TEXT,                         -- for SOW/AMENDMENT: the MSA they reference
  display_name      TEXT NOT NULL,
  contracting_entity_us TEXT NOT NULL,             -- our side (e.g. "Cognitive Capital Group LLC")
  contracting_entity_them TEXT NOT NULL,           -- their side
  signatory_us      TEXT NOT NULL,
  signatory_them    TEXT,
  status            TEXT NOT NULL,                 -- see CHECK below
  effective_date    DATE,                          -- when contract becomes binding
  termination_date  DATE,                          -- end date (if fixed-term)
  total_value       INTEGER,                       -- USD if applicable; NULL for NDAs etc.
  governing_law     TEXT,                          -- jurisdiction
  -- workflow markers
  drafted_at        DATETIME,
  sent_at           DATETIME,
  signed_us_at      DATETIME,
  signed_them_at    DATETIME,
  executed_at       DATETIME,                      -- when fully signed
  terminated_at     DATETIME,
  termination_reason TEXT,
  -- cross-DB references (loose)
  lead_id           TEXT,                          -- leads.db.lead.id that became this contract
  engagement_id     TEXT,                          -- engagements.db.engagement.id when contract spawns work
  -- file metadata
  vault_path        TEXT NOT NULL,                 -- relative path to source markdown
  pdf_path          TEXT,                          -- relative path to executed PDF (if signed)
  -- billing details (used by compose-invoice.py; populated from contract markdown frontmatter)
  bill_to_address   TEXT,                          -- multi-line address for invoice header
  bill_to_attention TEXT,                          -- "Attn: AP Department" line
  bill_to_email     TEXT,                          -- where invoice emails go
  billing_account   TEXT,                          -- google-workspace token label (e.g., 'ccg-phil')
  billing_payment_info TEXT,                       -- multi-line payment instructions on PDF
  billing_notes     TEXT,                          -- additional notes block on PDF
  reminder_days_before TEXT,                       -- '7' or 'NULL' to disable; calendar event days before due
  -- hourly billing config (only used when billing_mode = 'hourly')
  billing_mode      TEXT NOT NULL DEFAULT 'milestone',  -- 'milestone' | 'hourly' | 'subscription'
  hourly_rate       INTEGER,                            -- USD/hr (whole dollars)
  billing_calendar_account TEXT,                        -- google-workspace token for calendar (often = billing_account)
  billing_client_domains TEXT,                          -- comma-separated; events with attendee in these domains are billable IF Phil accepted
  billing_client_emails TEXT,                           -- comma-separated; explicit emails (additional to domain match)
  billing_work_block_pattern TEXT,                      -- title pattern marking solo billable focus blocks (e.g., 'InnoSync')
  billing_period_days INTEGER NOT NULL DEFAULT 30,      -- default billing window
  billing_round_to_minutes INTEGER NOT NULL DEFAULT 15, -- round each event duration up to this granularity
  created_at        DATETIME NOT NULL DEFAULT (datetime('now')),
  updated_at        DATETIME NOT NULL DEFAULT (datetime('now')),
  CHECK (contract_type IN ('MSA', 'SOW', 'NDA', 'LOI', 'AMENDMENT', 'OTHER')),
  CHECK (status IN (
    'DRAFT', 'IN_REVIEW', 'NEGOTIATING', 'SENT_FOR_SIGNATURE',
    'SIGNED_PARTIAL', 'EXECUTED', 'AMENDED', 'EXPIRED', 'TERMINATED', 'VOIDED'
  )),
  CHECK (terminated_at IS NULL OR status IN ('TERMINATED', 'VOIDED', 'EXPIRED'))
);

CREATE INDEX IF NOT EXISTS idx_contract_status ON contract(status);
CREATE INDEX IF NOT EXISTS idx_contract_type ON contract(contract_type);
CREATE INDEX IF NOT EXISTS idx_contract_parent ON contract(parent_contract_id);
CREATE INDEX IF NOT EXISTS idx_contract_termination ON contract(termination_date) WHERE termination_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contract_entity ON contract(entity_id);

-- ─── Contract amendments (1:N relationship from contract) ───
CREATE TABLE IF NOT EXISTS contract_amendment (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id       TEXT NOT NULL,
  amendment_number  INTEGER NOT NULL,              -- 1, 2, 3...
  description       TEXT NOT NULL,                 -- "increased scope by 2 weeks"
  value_delta       INTEGER,                       -- additional fee (or refund) in USD
  effective_date    DATE,
  signed_us_at      DATETIME,
  signed_them_at    DATETIME,
  vault_path        TEXT,                          -- per-amendment markdown
  pdf_path          TEXT,
  created_at        DATETIME NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (contract_id) REFERENCES contract(id) ON DELETE CASCADE,
  UNIQUE (contract_id, amendment_number)
);

CREATE INDEX IF NOT EXISTS idx_amendment_contract ON contract_amendment(contract_id);

-- ─── Payment schedule (per contract) ───
CREATE TABLE IF NOT EXISTS contract_payment (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id       TEXT NOT NULL,
  milestone         TEXT NOT NULL,                 -- "kickoff" | "midpoint" | "final" | "monthly-2026-05"
  amount            INTEGER NOT NULL,              -- USD
  due_trigger       TEXT NOT NULL,                 -- "signature" | "demo_accepted" | "delivery_accepted" | "calendar:2026-06-01"
  due_date          DATE,                          -- computed when trigger resolves
  invoice_id        TEXT,                          -- external invoice tracking ref
  invoiced_at       DATETIME,
  paid_at           DATETIME,
  paid_amount       INTEGER,                       -- in case of partial payment
  notes             TEXT,
  FOREIGN KEY (contract_id) REFERENCES contract(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_payment_contract ON contract_payment(contract_id);
CREATE INDEX IF NOT EXISTS idx_payment_due ON contract_payment(due_date) WHERE due_date IS NOT NULL AND paid_at IS NULL;

-- ─── Contract clauses of interest (auto-extracted by legal/contract-review skill) ───
CREATE TABLE IF NOT EXISTS contract_clause (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id       TEXT NOT NULL,
  clause_type       TEXT NOT NULL,                 -- "termination" | "indemnification" | "ip" | "confidentiality" | "limitation_of_liability" | "auto_renewal"
  text_excerpt      TEXT NOT NULL,                 -- the actual clause text
  flagged           INTEGER NOT NULL DEFAULT 0,    -- 1 if it deviates from default template
  flag_reason       TEXT,
  reviewer_notes    TEXT,
  FOREIGN KEY (contract_id) REFERENCES contract(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_clause_contract ON contract_clause(contract_id);
CREATE INDEX IF NOT EXISTS idx_clause_flagged ON contract_clause(flagged) WHERE flagged = 1;

-- ─── Useful views ───

-- Active contracts (executed and not terminated/expired)
CREATE VIEW IF NOT EXISTS v_active_contracts AS
SELECT
  id, display_name, contracting_entity_them, contract_type,
  total_value, effective_date, termination_date,
  CASE
    WHEN termination_date IS NULL THEN NULL
    ELSE julianday(termination_date) - julianday('now')
  END AS days_to_expiry
FROM contract
WHERE status = 'EXECUTED'
ORDER BY termination_date NULLS LAST;

-- Contracts expiring in next 90 days (renewal opportunity)
CREATE VIEW IF NOT EXISTS v_renewals_upcoming AS
SELECT
  id, display_name, contracting_entity_them, total_value, termination_date,
  julianday(termination_date) - julianday('now') AS days_to_expiry
FROM contract
WHERE status = 'EXECUTED'
  AND termination_date IS NOT NULL
  AND julianday(termination_date) - julianday('now') BETWEEN 0 AND 90
ORDER BY termination_date;

-- Outstanding payments (invoiced not paid OR not yet invoiced but past due trigger)
CREATE VIEW IF NOT EXISTS v_payments_outstanding AS
SELECT
  p.id, p.contract_id, c.display_name AS contract_name,
  p.milestone, p.amount, p.due_date, p.invoiced_at,
  CASE
    WHEN p.invoiced_at IS NOT NULL AND p.paid_at IS NULL THEN 'invoiced_unpaid'
    WHEN p.invoiced_at IS NULL AND p.due_date < date('now') THEN 'past_due_uninvoiced'
    ELSE 'pending'
  END AS payment_status
FROM contract_payment p
JOIN contract c ON c.id = p.contract_id
WHERE p.paid_at IS NULL
  AND (p.invoiced_at IS NOT NULL OR p.due_date < date('now'))
ORDER BY p.due_date;

-- Flagged clauses (for legal review surface in QBR/standup)
CREATE VIEW IF NOT EXISTS v_flagged_clauses AS
SELECT
  cl.id, cl.contract_id, c.display_name AS contract_name,
  cl.clause_type, cl.flag_reason, cl.text_excerpt
FROM contract_clause cl
JOIN contract c ON c.id = cl.contract_id
WHERE cl.flagged = 1 AND c.status IN ('DRAFT', 'IN_REVIEW', 'NEGOTIATING')
ORDER BY c.id, cl.clause_type;
