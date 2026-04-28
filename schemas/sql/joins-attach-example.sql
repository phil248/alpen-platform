-- Cross-DB joins use ATTACH DATABASE since SQLite cannot enforce foreign
-- keys across separate database files.
--
-- Example: a single query joining lead → contract → engagement to produce
-- a full-pipeline overview.

ATTACH DATABASE '~/.local/state/alpen/sqlite/leads.db'       AS leads;
ATTACH DATABASE '~/.local/state/alpen/sqlite/contracts.db'   AS contracts;
ATTACH DATABASE '~/.local/state/alpen/sqlite/engagements.db' AS engagements;

-- The full chain: lead → contract → engagement
SELECT
  l.id              AS lead_id,
  l.display_name    AS lead_name,
  l.value_estimate  AS lead_value,
  l.stage           AS lead_stage,
  c.id              AS contract_id,
  c.contract_type,
  c.status          AS contract_status,
  c.total_value     AS contract_value,
  e.id              AS engagement_id,
  e.status          AS engagement_status,
  e.health_color
FROM leads.lead              l
LEFT JOIN contracts.contract c ON c.id = l.contract_id
LEFT JOIN engagements.engagement e ON e.id = l.engagement_id
ORDER BY l.created_at DESC;

-- Pipeline value by lead-stage with conversion-to-engagement metric
SELECT
  l.stage,
  COUNT(*) AS leads,
  SUM(COALESCE(l.value_estimate, 0)) AS total_pipeline_value,
  SUM(CASE WHEN e.id IS NOT NULL THEN 1 ELSE 0 END) AS converted_to_engagement,
  SUM(CASE WHEN e.id IS NOT NULL THEN COALESCE(e.total_value, 0) ELSE 0 END) AS realized_value
FROM leads.lead l
LEFT JOIN engagements.engagement e ON e.id = l.engagement_id
GROUP BY l.stage
ORDER BY
  CASE l.stage
    WHEN 'WON' THEN 1
    WHEN 'NEGOTIATING' THEN 2
    WHEN 'PROPOSED' THEN 3
    WHEN 'SCOPED' THEN 4
    WHEN 'DISCOVERED' THEN 5
    WHEN 'ENGAGED' THEN 6
    WHEN 'QUALIFIED' THEN 7
    WHEN 'NEW' THEN 8
    WHEN 'LOST' THEN 9
    WHEN 'DISQUALIFIED' THEN 10
  END;

-- Engagements with their underlying contract status (catch out-of-sync state)
SELECT
  e.id, e.display_name, e.status AS engagement_status,
  c.id AS contract_id, c.status AS contract_status,
  CASE
    WHEN e.status = 'ACTIVE' AND c.status != 'EXECUTED' THEN 'WARNING_active_engagement_without_executed_contract'
    WHEN e.status = 'CLOSED' AND c.status = 'EXECUTED' THEN 'WARNING_closed_engagement_with_active_contract'
    ELSE 'ok'
  END AS sync_status
FROM engagements.engagement e
JOIN contracts.contract c ON c.id = e.contract_id
WHERE e.status NOT IN ('CANCELLED');
