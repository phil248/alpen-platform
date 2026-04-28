-- ip-watch.db — Trademark + patent monitoring (Alpen IP)
-- Source data: USPTO TSDR (trademarks) + USPTO PEDS (patents)
-- v0.1: trademarks via TSDR; patents v0.2

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

-- Watched marks/applications (Phil's IP that should be monitored for status changes)
CREATE TABLE IF NOT EXISTS watched_mark (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  serial_number   TEXT NOT NULL UNIQUE,            -- USPTO trademark serial number
  mark_text       TEXT,                            -- the actual trademark text
  owner           TEXT,                            -- registrant name as shown on USPTO
  status          TEXT,                            -- last known status text
  status_date     DATE,                            -- last known status date
  filing_date     DATE,
  registration_date DATE,
  -- monitoring
  notes           TEXT,
  active          INTEGER NOT NULL DEFAULT 1,
  added_at        DATETIME NOT NULL DEFAULT (datetime('now')),
  last_checked_at DATETIME,
  CHECK (active IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_watched_active ON watched_mark(active) WHERE active = 1;

-- Status change events (1:N from watched_mark)
CREATE TABLE IF NOT EXISTS status_event (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  watched_mark_id INTEGER NOT NULL,
  event_date      DATE NOT NULL,
  event_type      TEXT NOT NULL,                   -- e.g., "Office Action", "Approved for Pub", "Registered"
  description     TEXT,
  detected_at     DATETIME NOT NULL DEFAULT (datetime('now')),
  reviewed_at     DATETIME,
  reviewed_decision TEXT,                          -- act | dismiss
  FOREIGN KEY (watched_mark_id) REFERENCES watched_mark(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_status_event_mark ON status_event(watched_mark_id);
CREATE INDEX IF NOT EXISTS idx_status_event_unreviewed ON status_event(reviewed_at) WHERE reviewed_at IS NULL;

-- Saved searches for prior-art / similar-mark monitoring (text-search saved query)
CREATE TABLE IF NOT EXISTS saved_search (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  query           TEXT NOT NULL,
  search_type     TEXT NOT NULL,                   -- mark_text | owner | class
  notes           TEXT,
  active          INTEGER NOT NULL DEFAULT 1,
  created_at      DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_saved_search_active ON saved_search(active) WHERE active = 1;

-- Useful views
CREATE VIEW IF NOT EXISTS v_marks_active AS
SELECT id, serial_number, mark_text, owner, status, status_date, filing_date, last_checked_at
FROM watched_mark
WHERE active = 1
ORDER BY status_date DESC NULLS LAST;

CREATE VIEW IF NOT EXISTS v_unreviewed_events AS
SELECT
  e.id, e.watched_mark_id, m.serial_number, m.mark_text,
  e.event_date, e.event_type, e.description
FROM status_event e
JOIN watched_mark m ON m.id = e.watched_mark_id
WHERE e.reviewed_at IS NULL
ORDER BY e.event_date DESC;
