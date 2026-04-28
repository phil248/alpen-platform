---
name: transaction-logger
description: Log a transaction (trade, RSU vest, distribution, capital call, dividend) into the ledger. Use after any change in holdings. Writes to ~/.local/state/alpen/sqlite/transactions.db and updates positions.db.
---

# transaction-logger

## Status: stub (v0.1)

## Intent

Single entry point for adding any transaction. Updates the transaction ledger AND the current positions table atomically. Designed so `transaction-logger` is the only writer to either DB — everything else reads.

## Inputs

- Transaction details (date, action, asset, units, price, custodian, fees)
- Optional: source PDF (auto-routed via `statement-extractor`)

## Outputs

- New row in `~/.local/state/alpen/sqlite/transactions.db`
- Updated row in `~/.local/state/alpen/sqlite/positions.db`
- (Optional) double-entry journal entry handed to upstream `finance/journal-entry` skill

## Transaction types (v0.1)

- `BUY` / `SELL` — equities, ETFs, mutual funds, crypto
- `DIVIDEND` — cash or reinvested
- `INTEREST` — bonds, money market
- `RSU_VEST` — equity comp; tracks ordinary income basis
- `OPTION_EXERCISE` — strike + spread
- `CAP_CALL` — private fund capital call
- `DISTRIBUTION` — private fund distribution (return of capital + carry)
- `TRANSFER` — between own accounts (no tax event)

## v0.1 limitation

No tax-lot tracking yet. Pre-trade tax impact analyzer planned for v0.2.
