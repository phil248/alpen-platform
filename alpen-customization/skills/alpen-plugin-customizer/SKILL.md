---
name: alpen-plugin-customizer
description: >
  Customize a Claude Code plugin for an Alpen Platform tenant. Pre-fills
  ~~ placeholders from tenants/<tenant-id>/placeholders.yaml when values
  exist; falls back to AskUserQuestion for unset placeholders. Forked from
  anthropics/knowledge-work-plugins/cowork-plugin-management/cowork-plugin-customizer
  to work in plain Claude Code (no Cowork desktop required).
  Use when: customize plugin, set up plugin, configure plugin, tailor plugin
  for tenant, configure plugin connectors, run alpen customizer.
---

# Alpen Plugin Customization

Customize a Claude Code plugin for an Alpen Platform tenant. Adapts a generic
plugin template into a tenant-specific deployment by replacing `~~` placeholders
with values sourced from the tenant's `placeholders.yaml` (or asked
interactively when no value is present).

## Differences vs. upstream `cowork-plugin-customizer`

| Aspect | Upstream | This (Alpen) |
|---|---|---|
| Plugin path discovery | `find mnt/.local-plugins mnt/.plugins` (Cowork mounts) | `~/Winnie/alpen-platform/<plugin>/` or any local path passed by user |
| Pre-fill source | None (always prompts user via Knowledge MCPs + questions) | `tenants/<tenant-id>/placeholders.yaml` first; prompt only on misses |
| Cowork-only abort | Hard abort if mounts not found | Removed |
| Output packaging | `.plugin` zip in `outputs/` | Local commit in the fork repo |
| Compatibility note | Cowork desktop required | Plain Claude Code (no special environment) |

Everything else (the customization workflow, placeholder substitution,
MCP connector handling) follows the same pattern.

## Customization Workflow

### Phase 0: Locate plugin + identify tenant

1. **Locate the plugin** — accept path argument or ask. Prefer `~/Winnie/alpen-platform/<plugin-name>/`.
   - Verify with: `find ~/Winnie/alpen-platform -maxdepth 2 -type d -name "<plugin>"`.
   - If not found in fork repo, ask user for full path. Do not abort.

2. **Identify tenant** — default to `phil-howard` if running on Phil's machine; otherwise ask.
   - Tenant config lives at `~/Winnie/alpen-platform/tenants/<tenant-id>/`.
   - Verify `placeholders.yaml` exists; if not, fall back to upstream-style "ask everything" mode.

3. **Determine customization mode** — same as upstream:
   - **Generic plugin setup** — `~~` placeholders found → default mode.
   - **Scoped customization** — user named a specific part of the plugin.
   - **General customization** — no `~~` and user wants broad changes.

### Phase 1: Load placeholder pack + plugin scan

1. **Load** `tenants/<tenant-id>/placeholders.yaml`. Parse the two sections:
   - `upstream:` — values for the 46 placeholders defined by the upstream marketplace
   - `alpen_extensions:` — values for Alpen-introduced placeholders (`~~alpen-*`, `~~ccg-*`, etc.)

2. **Grep** the target plugin for placeholders:
   ```
   grep -rnE '~~[A-Za-z0-9_-]+' <plugin-path> --include='*.md' --include='*.json'
   ```

3. **Classify** each placeholder occurrence:
   - **Pre-fillable** — name matches a non-empty key in the placeholder pack.
   - **Skip** — name matches a key but the value is empty (`""`) or `null` → leave the `~~` in place; document in summary as "intentionally unset for this tenant."
   - **Unknown** — name has no entry in the pack → defer to Phase 3 (ask user).

### Phase 2: Build the todo list

For each placeholder occurrence, plan the action: substitute, skip, or ask.
Group by theme (Communication, Productivity, Sales, etc.) for the user-facing
todo summary. Use plain-English item titles, not file/line references.

### Phase 3: Apply substitutions

1. **Pre-fill from pack** — for every `Pre-fillable` occurrence, edit the file
   to replace `~~<name>` with the pack value. Make a single commit per
   plugin: `chore(<plugin>): customize for <tenant-id> via alpen placeholders`.

2. **Ask for unknowns** — use AskUserQuestion. After answer, persist the new
   key+value back into `tenants/<tenant-id>/placeholders.yaml` so future
   customizations pre-fill it.

3. **Skip empties** — leave `~~<name>` in place; report as such in the summary.

### Phase 4: Connect missing MCPs

Scan the plugin's `.mcp.json` for connectors that point to vendors the tenant
doesn't have OAuth wired up for yet. Suggest connection steps but do NOT
auto-connect (OAuth requires interactive browser).

For each unconnected connector:
- If the tenant config (in `~/Winnie/alpen-platform/tenants/<tenant-id>/config.yaml`,
  if it exists) declares the vendor as enabled, prompt user to OAuth.
- If not declared, mark as "skip — vendor not in tenant stack."

## Summary output

```markdown
## Customized: <plugin-name> for <tenant-id>

### From placeholder pack (auto-filled)
- `~~email` → `Gmail`
- `~~calendar` → `Google Calendar`
- `~~chat` → `Telegram`
…

### From your answers
- `~~mystery-thing` → `whatever you said`

### Intentionally unset (left as `~~`)
- `~~Jira` (tenant doesn't use Jira)
- `~~CRM` (markdown-first; Twenty optional later)

### MCP connectors
- ✓ Already connected: gmail, calendar, drive
- ⚠ Skipped (not in tenant stack): hubspot, close, clay
- → Action needed (OAuth required): slack
```

## Important rules (preserved from upstream)

- **Never rename** the plugin or skill being customized.
- **Never expose** `~~` syntax in user-facing prose — frame in plain language.
- **Persist new placeholder values** to `placeholders.yaml` so future runs pre-fill.
- **Single commit per plugin** customized; don't mix multi-plugin changes.

## Examples

### Customize the sales plugin for phil-howard tenant

```bash
# From a Claude Code session:
> Customize the sales plugin

# Customizer:
# 1. Locates ~/Winnie/alpen-platform/sales/
# 2. Loads ~/Winnie/alpen-platform/tenants/phil-howard/placeholders.yaml
# 3. Greps 14 ~~ occurrences in sales/skills/*/SKILL.md
# 4. Pre-fills (e.g., ~~CRM stays as ~~CRM since pack has empty value;
#    ~~email → Gmail; ~~calendar → Google Calendar; etc.)
# 5. Commits: chore(sales): customize for phil-howard via alpen placeholders
# 6. Reports: 11 substitutions, 3 left unset, no MCPs needing OAuth
```

### Customize the legal plugin and add Alpen tier-ladder context

```bash
> Customize the legal plugin and inject our tier-1/2/3 SOW templates
```

The customizer pre-fills upstream `~~` placeholders, and additionally
injects `~~alpen-tier-1-name`, `~~alpen-tier-2-fee`, etc. wherever they
appear in our customized SOW skill files.

## Open implementation gaps (v0.1)

- **Auto-MCP-connect** — Phase 4 currently advises only; doesn't trigger OAuth.
  Defer until we ship an `alpen init` CLI that handles tenant onboarding flows.
- **Dry-run mode** — would be useful to preview substitutions without writing.
  Add `--dry-run` flag once we move from SKILL to CLI.
- **Multi-tenant** — single-tenant only for v0.1; defer until customer #2.
- **Conflict resolution on upstream merge** — substituted plugin files will
  conflict on every `git merge upstream/main`. Solve by branch-based pattern
  in v0.2 (keep `main` clean, work on `alpen` branch).
