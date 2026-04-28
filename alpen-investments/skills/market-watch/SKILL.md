---
name: market-watch
description: Daily market digest filtered to YOUR actual holdings, not generic market news. Surfaces material events for currently-held positions. Use as part of daily standup or on-demand. Reads positions.db; queries news/filings APIs.
---

# market-watch

## Status: stub (v0.1)

## Intent

Solve the "I get 200 market emails a day, none about my portfolio" problem. Read current positions, fan out to news + SEC filings + earnings calendar APIs filtered by ticker, surface the 5-10 events that actually matter.

## Inputs

- `~/.local/state/alpen/sqlite/positions.db` — current holdings
- News APIs (e.g., Bloomberg Open API if licensed; otherwise free RSS aggregators)
- SEC EDGAR for 8-K / 10-Q filings
- Earnings calendar (free public sources)

## Outputs

- `${VAULT}/HFO/Investments/Market-Watch/YYYY-MM-DD-watch.md`
- Telegram DM or Gmail draft to principal if any event flagged as material

## What counts as "material" (v0.1 heuristic)

- 8-K filing for any held position
- Earnings beat/miss > 5% on consensus
- Pre-market / after-hours move > 4% on a held name
- Analyst rating change at major bank
- M&A announcement involving a held name
- Sector-wide news affecting > 20% of portfolio NAV

## v0.1 limitation

Generic news APIs only. Bloomberg / FactSet integration is v0.2+. Filing ingest works against EDGAR free tier.
