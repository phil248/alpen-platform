---
name: portfolio-tracker
description: Snapshot consolidated positions across custodians; detect allocation drift vs. target. Use when running weekly portfolio review, checking allocation drift, looking up current position in a specific holding, or before any rebalancing decision. Writes to ~/.local/state/alpen/sqlite/positions.db.
---

# portfolio-tracker

## Status: stub (v0.1)

## Intent

Produce a single, current view of all positions across all custodians (Schwab, Fidelity, private fund admins, crypto wallets, etc.). Compare to target allocation. Surface drift exceeding configurable threshold.

## Inputs

- `~/.local/state/alpen/sqlite/positions.db` — current positions table (asset, custodian, units, market_value, last_updated)
- `~/.local/state/alpen/sqlite/transactions.db` — transaction ledger (for cross-checking position deltas)
- `${VAULT}/HFO/Investments/Allocation-Targets.md` — target allocation by asset class
- Optional: live price fetch via `beanprice` (Beancount ecosystem) or vendor MCP

## Outputs

- `${VAULT}/HFO/Investments/Snapshots/YYYY-MM-DD-snapshot.md` — markdown snapshot
- Updated `positions.db` rows
- Drift alerts surfaced in `${VAULT}/_Inbox/YYYY-MM-DD-portfolio-drift.md` if any class is >5pp from target

## Workflow (planned)

1. Read current positions from `positions.db`
2. Refresh prices (if live source connected)
3. Compute consolidated allocation by asset class
4. Compare to targets; flag drift
5. Emit snapshot markdown + drift inbox file

## v0.1 limitation

No live price fetch wired. Operates on whatever was last imported via `statement-extractor`. Suitable for monthly snapshots, not daily.
