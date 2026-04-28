-- regwatch.db — Regulatory monitoring (Alpen IP)
-- Source data: Federal Register API + Regulations.gov + CourtListener
-- Local cache only; this is NOT a source of truth — it's a memo of what
-- the Alpen platform has surfaced to the user.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

-- Subscriptions (Phil's queries that should run on a schedule)
CREATE TABLE IF NOT EXISTS subscription (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  query           TEXT NOT NULL,                   -- "AI healthcare workplace wellness" etc.
  source          TEXT NOT NULL,                   -- federal_register | regulations_gov | courtlistener
  agencies        TEXT,                            -- comma-separated agency abbreviations to filter
  active          INTEGER NOT NULL DEFAULT 1,
  created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
  notes           TEXT,
  CHECK (source IN ('federal_register', 'regulations_gov', 'courtlistener'))
);

CREATE INDEX IF NOT EXISTS idx_subscription_active ON subscription(active);

-- Alerts (matches found per subscription)
CREATE TABLE IF NOT EXISTS alert (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  subscription_id INTEGER,                         -- NULL if from ad-hoc search
  source          TEXT NOT NULL,
  external_id     TEXT NOT NULL,                   -- federal_register doc number etc.
  title           TEXT NOT NULL,
  agency          TEXT,
  publication_date DATE,
  url             TEXT,
  abstract        TEXT,
  -- workflow
  surfaced_at     DATETIME NOT NULL DEFAULT (datetime('now')),
  reviewed_at     DATETIME,
  review_decision TEXT,                            -- relevant | irrelevant | act_on
  routed_to       TEXT,                            -- which dept / person took action
  notes           TEXT,
  FOREIGN KEY (subscription_id) REFERENCES subscription(id) ON DELETE SET NULL,
  UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_alert_subscription ON alert(subscription_id);
CREATE INDEX IF NOT EXISTS idx_alert_pubdate ON alert(publication_date DESC);
CREATE INDEX IF NOT EXISTS idx_alert_unreviewed ON alert(reviewed_at) WHERE reviewed_at IS NULL;

-- Useful view: unreviewed alerts in pub-date order
CREATE VIEW IF NOT EXISTS v_alerts_unreviewed AS
SELECT id, source, agency, publication_date, title, url, abstract
FROM alert
WHERE reviewed_at IS NULL
ORDER BY publication_date DESC, surfaced_at DESC;

-- Useful view: recent alerts marked actionable
CREATE VIEW IF NOT EXISTS v_alerts_actionable AS
SELECT id, source, agency, publication_date, title, routed_to, notes
FROM alert
WHERE review_decision = 'act_on'
ORDER BY publication_date DESC
LIMIT 50;
