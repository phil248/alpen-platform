-- voc-signals.db — Voice of Customer signal mining over meeting transcripts
-- Source of truth: ${VAULT}/**/Plaud-Recordings/*.md
-- Per feedback_alpen_storage_patterns.md: regenerable from transcripts via voc-extract.py

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

-- ─── Per-transcript record (one per processed file) ───
CREATE TABLE IF NOT EXISTS transcript (
  id              TEXT PRIMARY KEY,                -- file slug (basename without .md)
  tenant_id       TEXT NOT NULL,
  entity_id       TEXT,                            -- ccg | alpen-tech | kroger | personal (best-guess from path)
  vault_path      TEXT NOT NULL,                   -- relative path to source markdown
  meeting_date    DATE,                            -- from frontmatter `date:` field
  meeting_title   TEXT,                            -- from frontmatter `title:`
  duration_text   TEXT,                            -- "~64 min" — kept verbatim, no parse
  -- linkage to leads.db (loose)
  lead_id         TEXT,                            -- if transcript was attributed to a specific lead
  client_name     TEXT,                            -- best-guess client/account name
  -- processing metadata
  extracted_at    DATETIME NOT NULL DEFAULT (datetime('now')),
  extractor_version TEXT NOT NULL,                 -- versioned so re-extraction is detectable
  signal_count    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_transcript_date ON transcript(meeting_date DESC);
CREATE INDEX IF NOT EXISTS idx_transcript_entity ON transcript(entity_id);
CREATE INDEX IF NOT EXISTS idx_transcript_lead ON transcript(lead_id) WHERE lead_id IS NOT NULL;

-- ─── Signals (1:N from transcript) ───
CREATE TABLE IF NOT EXISTS signal (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  transcript_id   TEXT NOT NULL,
  -- what kind of signal
  signal_type     TEXT NOT NULL,                   -- see CHECK below
  severity        TEXT NOT NULL,                   -- low | medium | high | critical
  -- the signal content
  description     TEXT NOT NULL,                   -- one-sentence summary
  evidence        TEXT,                            -- verbatim or paraphrased quote from transcript
  topic           TEXT,                            -- the section/topic the signal came from (e.g., "Strategy, Business Model")
  -- attribution
  attributed_to_lead_id TEXT,                      -- specific lead this signal is about (if differs from transcript-level)
  attributed_to_account TEXT,                      -- e.g., "WebMD", "Roche" — free-text since may not match a lead
  -- routing
  routed_to_dept  TEXT,                            -- which dept consumes this (revenue|delivery|cs|product|legal)
  routed_at       DATETIME,
  task_id         TEXT,                            -- google task id when this signal has been turned into a follow-up task
  task_created_at DATETIME,
  resolved_at     DATETIME,                        -- set when the signal has been acted on
  resolution      TEXT,
  CHECK (signal_type IN (
    'expansion',          -- account is interested in more / new scope
    'objection',          -- pushback or skepticism
    'churn_risk',         -- indicators they may leave / disengage
    'feedback',           -- product feedback worth product team
    'competitive',        -- mention of competitor or comparison
    'expansion_blocker',  -- they would buy more if X
    'commitment',         -- they verbally committed to something
    'ask',                -- they asked for something specific
    'praise',             -- positive feedback
    'risk',               -- engagement risk (Delivery dept)
    'opportunity'         -- general opportunity not fitting above
  )),
  CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  FOREIGN KEY (transcript_id) REFERENCES transcript(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_signal_transcript ON signal(transcript_id);
CREATE INDEX IF NOT EXISTS idx_signal_type ON signal(signal_type);
CREATE INDEX IF NOT EXISTS idx_signal_severity ON signal(severity);
CREATE INDEX IF NOT EXISTS idx_signal_account ON signal(attributed_to_account);
CREATE INDEX IF NOT EXISTS idx_signal_lead ON signal(attributed_to_lead_id) WHERE attributed_to_lead_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_signal_unresolved ON signal(resolved_at) WHERE resolved_at IS NULL;

-- ─── Useful views ───

-- Recent unresolved signals by severity
CREATE VIEW IF NOT EXISTS v_signals_unresolved AS
SELECT
  s.id, s.signal_type, s.severity,
  s.description, s.attributed_to_account, s.routed_to_dept,
  t.meeting_date, t.meeting_title, t.client_name
FROM signal s
JOIN transcript t ON t.id = s.transcript_id
WHERE s.resolved_at IS NULL
ORDER BY
  CASE s.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
  t.meeting_date DESC;

-- Expansion signals by account (Sales action surface)
CREATE VIEW IF NOT EXISTS v_expansion_by_account AS
SELECT
  COALESCE(s.attributed_to_account, t.client_name, 'unknown') AS account,
  COUNT(*) AS expansion_signals,
  MAX(t.meeting_date) AS most_recent_date,
  GROUP_CONCAT(s.description, ' • ') AS recent_evidence
FROM signal s
JOIN transcript t ON t.id = s.transcript_id
WHERE s.signal_type IN ('expansion', 'commitment', 'ask')
  AND s.resolved_at IS NULL
GROUP BY account
ORDER BY expansion_signals DESC, most_recent_date DESC;

-- Objections + competitive intel (qualifier feedback loop)
CREATE VIEW IF NOT EXISTS v_objections_recent AS
SELECT
  s.signal_type, s.description, s.evidence, s.attributed_to_account,
  t.meeting_date, t.meeting_title
FROM signal s
JOIN transcript t ON t.id = s.transcript_id
WHERE s.signal_type IN ('objection', 'expansion_blocker', 'competitive')
  AND s.resolved_at IS NULL
ORDER BY t.meeting_date DESC
LIMIT 50;

-- Churn-risk surface for CS
CREATE VIEW IF NOT EXISTS v_churn_risk AS
SELECT
  s.id, s.description, s.evidence, s.attributed_to_account,
  s.severity, t.meeting_date, t.meeting_title
FROM signal s
JOIN transcript t ON t.id = s.transcript_id
WHERE s.signal_type = 'churn_risk' AND s.resolved_at IS NULL
ORDER BY
  CASE s.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
  t.meeting_date DESC;

-- Feedback to forward to Product team
CREATE VIEW IF NOT EXISTS v_product_feedback AS
SELECT
  s.id, s.description, s.evidence, s.attributed_to_account,
  s.routed_to_dept, t.meeting_date, t.meeting_title
FROM signal s
JOIN transcript t ON t.id = s.transcript_id
WHERE s.signal_type IN ('feedback', 'ask') AND s.resolved_at IS NULL
ORDER BY t.meeting_date DESC;
