# Multi-tenant — known issues (v0.1 = single-tenant deployable)

The Alpen Platform is intentionally designed as **single-tenant deployable** for v0.1 (per `Alpen-platform-v0.1-architecture.md`). Each tenant runs the platform in their own environment — Phil's machine, an acquired customer's machine, etc.

Running multiple tenants on the same machine surfaces footguns the architecture has not yet hardened. Documented here so they don't bite by surprise.

## Footgun 1 — shared default `state_dir`

**Symptom:** running `bin/regenerate-*-index.py --tenant <other>` on a machine where `tenants/<other>/config.yaml` has `state_dir: "~/.local/state/alpen"` (the default from `alpen-init.py`) writes to the SAME SQLite DBs as another tenant whose config also defaults to `~/.local/state/alpen`. Data labels (`tenant_id` column) get overwritten.

**Reproducer (don't run on production data):**

```bash
# Bootstrap a second tenant with default state_dir (same as phil-howard)
bin/alpen-init.py --tenant-id demo --from-args ...

# Run regenerator for that tenant
bin/regenerate-leads-index.py --tenant demo

# phil-howard's leads.db is now labeled tenant_id='demo' for all rows
```

**Mitigation in v0.1:**

`bin/_regenerator_lib.py:tenant_state_dir()` reads `tenant.state_dir` from the config and uses `<state_dir>/sqlite/<name>.db`. This works as long as each tenant has a UNIQUE state_dir. The bug only manifests when two tenants share the default.

**Workaround for the focused multi-tenant session:**

In `bin/alpen-init.py`, change the default state_dir from
```
~/.local/state/alpen
```
to
```
~/.local/state/alpen/<tenant-id>
```
so two tenants on the same machine get separate state dirs by default. Then `tenant_state_dir()` resolves correctly without manual config edits.

**Why deferred:** this is one of several multi-tenant decisions (state isolation, log isolation, vault isolation, RAG-store isolation, MCP-server-per-tenant vs. shared, telemetry segregation) that benefit from being designed together rather than patched piecemeal. Multi-tenant is a Phase 2 architectural sprint, not a v0.1 hotfix.

## Footgun 2 — vault path defaulting

The regenerators read the source data dir from `VAULT_PATH` env var (defaulting to Phil's iCloud Obsidian path) — not from the tenant config. So `--tenant <other>` reads from Phil's vault unless `VAULT_PATH` is overridden.

This compounds Footgun 1: a "demo-corp" run reads phil-howard's CCG opportunities AND writes them to phil-howard's leads.db (since both share the default state_dir).

**Mitigation in v0.1:** scripts could be patched to read `tenant.vault_path` from the tenant config. The same multi-tenant session should fix this.

## Footgun 3 — MCP server registrations are global

`claude mcp add --scope user voc <python> <server.py>` registers ONE voc server for the whole user's Claude Code interactive sessions. Same for regwatch, ip-watcher, hfo_rag, etc. Multi-tenant on same machine would need:

- Per-tenant MCP server registration namespacing (e.g., `voc-phil-howard`, `voc-demo-corp`)
- Or run each tenant in a different `$HOME` to isolate `.claude.json`

## What's safe in v0.1

- **Single tenant per machine.** Phil's machine = phil-howard. An acquired customer's machine = their tenant. No cross-tenant collisions because each tenant owns the whole machine.
- **Smoke-testing alpen-init** by creating a test tenant THEN cleaning it up before running any regenerators against it (or running with `--source-dir <isolated>` and `--state-dir <isolated>` env override). Validation steps don't touch state DBs.

## When this gets fixed

The multi-tenant architectural session should produce:

1. State-dir defaults that are tenant-namespaced (`~/.local/state/alpen/<tenant-id>`)
2. Vault-path source-of-truth = tenant config, not env var
3. MCP server registration strategy (per-tenant namespacing OR per-tenant home)
4. Telemetry isolation (per-tenant `invocations.jsonl`)
5. RAG store isolation (per-tenant DB; shared embedding model OK)

Until then, treat the platform as single-tenant per machine. The bug will sit here until that session.

**Decided 2026-04-28.** Surfaced by the alpen-init smoke test for issue #5 in the priority list.
