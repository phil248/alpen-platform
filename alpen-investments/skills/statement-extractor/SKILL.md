---
name: statement-extractor
description: Extract structured trades and positions from custodian / fund admin / brokerage PDFs. Composite of pdfplumber + Camelot + Claude. Routes extracted transactions to transaction-logger. Use when a new statement PDF lands; biggest moat opportunity in alpen-investments dept.
---

# statement-extractor

## Status: stub (v0.1)

## Intent

The single biggest moat opportunity in the CIO department: turn arbitrary custodian/fund-admin PDFs into structured transactions + positions, with high enough accuracy that no human re-keying is needed. No usable OSS exists at quality bar; commercial options (Ocrolus, Canopy) are expensive and don't fit the single-tenant deployable model.

## Inputs

- A statement PDF dropped into `${VAULT}/HFO/Investments/_incoming/` (WatchPath-triggered)
- Optional: prior parsed statements from same custodian (for format learning)

## Outputs

- Parsed transactions handed to `transaction-logger`
- Parsed positions reconciled against current `positions.db`
- Original PDF moved to `${VAULT}/HFO/Investments/Statements/<custodian>/<period>.pdf`
- Reconciliation report at `${VAULT}/HFO/Investments/Reconciliations/YYYY-MM-DD-<custodian>.md`

## Workflow (planned)

1. Detect custodian from PDF header / filename
2. Apply `pdfplumber` for text + Camelot for tables
3. Hand text + table data to Claude with custodian-specific extraction template
4. Parse transactions → JSON schema
5. Reconcile parsed positions vs. current `positions.db` (flag mismatches)
6. Send transactions to `transaction-logger`
7. Move PDF to permanent vault location, write reconciliation report

## Custodian templates (v0.1)

- Schwab — TBD
- Fidelity NetBenefits — TBD
- (private fund admin TBD)
- (crypto exchanges TBD)

## v0.1 limitation

This SKILL describes the workflow; no extraction templates exist yet. Each custodian needs a one-time template build (typically 2-4 hours per format). Plan: build templates as statements arrive, not pre-emptively.
