# alpen-investments

Family-office Chief Investment Officer (CIO) capability. Closes the "is this really a family office?" gap with the smallest possible footprint: track positions, log transactions, run manager DD, and surface market events filtered to actual holdings.

## Status

**v0.1 — scaffold only.** SKILL.md files are stubs that document the intended workflow and the data they read/write. No bespoke MCP servers wired yet. Refinement comes from real usage on Phil's HFO account before this graduates to a production capability.

## When to use

| Capability | When |
|---|---|
| `portfolio-tracker` | Weekly snapshot of consolidated positions across custodians; allocation drift detection |
| `manager-dd` | Before any new fund / GP commitment; produces an IC memo from public + private sources |
| `transaction-logger` | After any trade, RSU vesting, distribution, or capital call |
| `market-watch` | Daily digest filtered to *your actual holdings*, not generic market news |
| `statement-extractor` | Custodian / fund PDFs → structured trades + positions; biggest moat opportunity in this dept |

## Data stores

- `~/.local/state/alpen/sqlite/positions.db` — current consolidated positions (custodian-aggregated)
- `~/.local/state/alpen/sqlite/transactions.db` — transaction ledger
- `${VAULT}/HFO/Investments/Statements/` — raw custodian PDFs (gitignored, encrypted at rest)
- `${VAULT}/HFO/Investments/IC-Memos/<manager-slug>.md` — manager DD memos
- RAG kind `hfo-investment` (private, ACL-gated to principal)

## Composition with other plugins

- **alpen-deep-research** — `manager-dd` invokes `client-content-inventory` orchestrator with `--subject <manager-name>` to deep-research GP track records, team backgrounds, fund vintages
- **finance** (upstream Anthropic plugin) — `transaction-logger` writes to the same ledger that `finance/journal-entry` reads; double-entry bookkeeping stays consistent
- **legal** (upstream) — `manager-dd` cross-references LP agreements via `legal/contract-review`

## Privacy

This plugin operates exclusively on private financial data. RAG kind `hfo-investment` MUST be ACL-gated. Vault paths under `HFO/Investments/` MUST be gitignored. Statement PDFs SHOULD be encrypted at rest (e.g., via `age` per the architecture spec).

## v0.1 → v0.2 backlog

1. Build `statement-extractor` MCP — composite of `pdfplumber` + Claude + tax-lot reconciliation. Biggest moat opportunity in the dept.
2. Wire `beanprice` (from Beancount ecosystem) for daily price fetch
3. Add Plaid MCP integration as optional bolt-on for liquid accounts
4. Add Schwab API + Fidelity NetBenefits scrapers
5. Cap-call email watcher (event-driven via `${VAULT}/HFO/Investments/_incoming` WatchPath)
6. Tax-lot analyzer (pre-trade tax impact)
