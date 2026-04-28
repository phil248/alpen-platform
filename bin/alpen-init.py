#!/usr/bin/env python3
"""Bootstrap a new Alpen Platform tenant.

Creates:
  tenants/<tenant-id>/config.yaml         — full tenant configuration
  tenants/<tenant-id>/placeholders.yaml   — placeholder stub (filled later
                                             by alpen-plugin-customizer or
                                             bin/alpen-customize.py)

Two modes:
  Interactive: walks the user through required inputs; prompts with sensible
               defaults; rejects malformed inputs with the same Pydantic
               models that bin/validate-tenant-config.py uses.
  Scripted:    `--from-args` accepts every required field via CLI flags for
               batch / CI use.

Usage (interactive):
  alpen-init.py --tenant-id acme-consulting

Usage (scripted, minimal):
  alpen-init.py --tenant-id acme-consulting \
                --tenant-name "Acme Consulting" \
                --tenant-type general-consulting \
                --principal-name "Jane Doe" \
                --principal-email jane@acme.example \
                --entity-id acme \
                --entity-name "Acme Consulting" \
                --entity-type general-consulting

After creation, runs validate-tenant-config.py automatically.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import yaml

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
TENANTS_DIR = PLATFORM_ROOT / "tenants"


# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_DEPARTMENTS = {
    "office-of-principal": {"enabled": True,  "model": "sonnet"},
    "finance":             {"enabled": True,  "model": "sonnet"},
    "investments":         {"enabled": False, "model": "sonnet"},
    "legal":               {"enabled": True,  "model": "sonnet"},
    "revenue":             {"enabled": True,  "model": "sonnet"},
    "delivery":            {"enabled": True,  "model": "sonnet"},
    "knowledge":           {"enabled": True,  "model": "haiku"},
    "operations":          {"enabled": True,  "model": "sonnet"},
}

# Sensible default schedules — shifted slightly later than Phil's so a new
# tenant doesn't immediately collide with HFO's cron landscape if both run
# on the same machine.
DEFAULT_SCHEDULES = {
    "cron": [
        {"id": "rag-ingest",       "cron": "30 3 * * *",   "agent": "rag-ingest", "runtime": "python"},
        {"id": "nightly-backup",   "cron": "30 2 * * *",   "agent": "nightly-backup", "runtime": "bash"},
        {"id": "regenerate-all",   "cron": "15 6 * * *",   "agent": "alpen-regenerate-all", "runtime": "bash"},
        {"id": "daily-briefing",   "cron": "45 6 * * 1-5", "agent": "daily-briefing"},
        {"id": "email-triage",     "cron": "35 7 * * 1-5", "agent": "email-triage"},
        {"id": "meeting-prep",     "cron": "20 7 * * 1-5", "agent": "meeting-prep"},
        {"id": "pipeline-review",  "cron": "0 8 * * 1",    "agent": "pipeline-review"},
        {"id": "daily-standup",    "cron": "42 7 * * *",   "agent": "daily-standup"},
    ],
    "watchpaths": [],
}


# ──────────────────────────────────────────────────────────────────────────────
# Interactive prompts
# ──────────────────────────────────────────────────────────────────────────────

def prompt(label: str, default: str | None = None, required: bool = True) -> str:
    suffix = f" [{default}]" if default else ""
    suffix = "" if not sys.stdin.isatty() else suffix
    while True:
        try:
            val = input(f"  {label}{suffix}: ").strip()
        except EOFError:
            val = ""
        if val:
            return val
        if default is not None:
            return default
        if not required:
            return ""
        print("  (required — please enter a value)")


def collect_interactive(tenant_id: str) -> dict:
    print(f"\n=== alpen-init: bootstrap tenant '{tenant_id}' ===")
    print("Press Enter to accept defaults shown in [brackets].\n")

    print("--- Tenant ---")
    tenant_name = prompt("Tenant display name", default=tenant_id.replace("-", " ").title())
    tenant_type = prompt("Tenant type [ai-consulting | brain-health-consulting | family-office | general-consulting | saas | agency]", default="general-consulting")
    timezone = prompt("Timezone (e.g., America/New_York)", default="America/New_York")
    locale = prompt("Locale", default="en-US")
    vault_default = f"~/Documents/{tenant_id}-vault"
    vault_path = prompt("Vault path (markdown source of truth)", default=vault_default)
    state_dir = prompt("State dir (NOT iCloud!)", default="~/.local/state/alpen")
    log_dir = prompt("Log dir", default="~/Library/Logs/alpen")

    print("\n--- Principal (the human running the show) ---")
    principal_name = prompt("Principal name")
    principal_email = prompt("Principal email")
    principal_id = prompt("Principal id (short, lowercase)", default=principal_name.split()[0].lower())

    print("\n--- First entity ---")
    entity_id = prompt("Entity id (short, lowercase, kebab-case)", default=tenant_id)
    entity_name = prompt("Entity display name", default=tenant_name)
    entity_type = prompt("Entity type [same as tenant type if singular]", default=tenant_type)
    entity_domain = prompt("Entity domain (optional)", default="", required=False)

    print("\n--- Departments ---")
    print("  (defaults: most enabled; investments OFF unless family-office)")
    family_office = (tenant_type == "family-office")
    deps = {
        name: {**cfg, "enabled": cfg["enabled"] or (name == "investments" and family_office)}
        for name, cfg in DEFAULT_DEPARTMENTS.items()
    }
    for name in deps:
        if deps[name]["enabled"]:
            ans = prompt(f"  Enable {name}? [y/n]", default="y", required=False)
            deps[name]["enabled"] = ans.lower().startswith("y")
        else:
            ans = prompt(f"  Enable {name}? [y/n]", default="n", required=False)
            deps[name]["enabled"] = ans.lower().startswith("y")

    return {
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "tenant_type": tenant_type,
        "timezone": timezone,
        "locale": locale,
        "vault_path": vault_path,
        "state_dir": state_dir,
        "log_dir": log_dir,
        "principal_id": principal_id,
        "principal_name": principal_name,
        "principal_email": principal_email,
        "entity_id": entity_id,
        "entity_name": entity_name,
        "entity_type": entity_type,
        "entity_domain": entity_domain,
        "departments": deps,
    }


def collect_from_args(args: argparse.Namespace) -> dict:
    return {
        "tenant_id": args.tenant_id,
        "tenant_name": args.tenant_name,
        "tenant_type": args.tenant_type,
        "timezone": args.timezone,
        "locale": args.locale,
        "vault_path": args.vault_path or f"~/Documents/{args.tenant_id}-vault",
        "state_dir": args.state_dir,
        "log_dir": args.log_dir,
        "principal_id": args.principal_id or args.principal_name.split()[0].lower(),
        "principal_name": args.principal_name,
        "principal_email": args.principal_email,
        "entity_id": args.entity_id,
        "entity_name": args.entity_name,
        "entity_type": args.entity_type,
        "entity_domain": args.entity_domain or "",
        "departments": DEFAULT_DEPARTMENTS,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Build artifacts
# ──────────────────────────────────────────────────────────────────────────────

def build_config(d: dict) -> dict:
    """Build the config.yaml dict from collected inputs."""
    state_dir = d["state_dir"]
    log_dir = d["log_dir"]
    return {
        "schema_version": "0.1",
        "tenant": {
            "id": d["tenant_id"],
            "name": d["tenant_name"],
            "type": d["tenant_type"],
            "timezone": d["timezone"],
            "locale": d["locale"],
            "vault_path": d["vault_path"],
            "state_dir": state_dir,
            "log_dir": log_dir,
            "created_at": date.today().isoformat(),
        },
        "principals": [{
            "id": d["principal_id"],
            "name": d["principal_name"],
            "role": "ceo",
            "scopes": [d["entity_id"]],
            "accounts": [{
                "kind": "gmail",
                "address": d["principal_email"],
                "mcp": "google",
            }],
        }],
        "entities": [{
            "id": d["entity_id"],
            "display_name": d["entity_name"],
            "type": d["entity_type"],
            **({"domain": d["entity_domain"]} if d["entity_domain"] else {}),
            "public": True,
            "tiers": [],  # tenant fills these per business model
            "templates_dir": f"templates/{d['entity_id']}/",
        }],
        "departments": d["departments"],
        "data_stores": {
            "rag": {
                "backend": "sqlite-vec",
                "embedding": {
                    "provider": "ollama",
                    "model": "nomic-embed-text",
                    "dimensions": 768,
                },
                "db_path": f"{state_dir}/rag.db",
                "kinds": [
                    {"id": "meeting-transcript", "private": False},
                    {"id": "voc-signals",         "private": False},
                    {"id": "sales-history",       "private": False},
                ],
            },
            "structured": {
                "backend": "sqlite",
                "db_dir": f"{state_dir}/sqlite/",
                "databases": [
                    {"id": "leads",        "path": "leads.db"},
                    {"id": "engagements",  "path": "engagements.db"},
                    {"id": "contracts",    "path": "contracts.db"},
                ],
            },
            "vault": {
                "backend": "filesystem",
                "path": d["vault_path"],
                "layout": "by-entity",
                "indices_dir": f"{state_dir}/indices/",
                "sync_excluded": ["*.db", "*.db-wal", "*.db-shm"],
            },
            "backup": {
                "nightly_targets": ["rag", "structured", "indices"],
                "weekly_targets": ["logs"],
                "destination": f"{log_dir.rsplit('/', 1)[0]}/backups/",
            },
        },
        "integrations": {
            "email":         {"primary": "google-workspace"},
            "calendar":      {"primary": "google-workspace"},
            "drive":         {"primary": "google-workspace"},
            "transcription": {"provider": "whisper-cpp"},
            "ocr":           {"provider": "tesseract"},
            "ai_models": {
                "primary": {
                    "provider": "anthropic",
                    "models": {
                        "sonnet": "claude-sonnet-4-6",
                        "haiku":  "claude-haiku-4-5",
                        "opus":   "claude-opus-4-7",
                    },
                },
                "embedding": {"provider": "ollama", "model": "nomic-embed-text"},
            },
            "optional": {
                "crm":         {"provider": "twenty",    "enabled": False},
                "pm":          {"provider": "plane",     "enabled": False},
                "bookkeeping": {"provider": "beancount", "enabled": False},
                "automation":  {"provider": "n8n",       "enabled": False},
            },
        },
        "templates": {
            "default_dir": "templates/default/",
            "override_resolution": "entity > tenant > default",
            "required": [
                "proposal-tier-1.md", "proposal-tier-2.md", "proposal-tier-3.md",
                "scope-questionnaire.yaml", "msa-template.md", "sow-template.md",
                "qbr-deck.md", "status-report.md", "kickoff-deck.md",
                "brand-voice.md",
            ],
        },
        "telemetry": {
            "enabled": True,
            "ledger": f"{log_dir}/invocations.jsonl",
            "sqlite": f"{log_dir}/invocations.db",
            "dashboard": {"enabled": True, "port": 5173},
            "expose_to_principal": True,
            "expose_to_customer": False,
            "privacy": {
                "redact_pii_in_summaries": True,
                "excluded_kinds": [],
            },
        },
        "schedules": DEFAULT_SCHEDULES,
        "features": {
            "multi_tenant": False,
            "advisory_board": True,
            "voice_of_customer": True,
            "expansion_signal_detection": True,
            "competitor_watch": True,
            "external_crm": False,
            "external_pm": False,
            "external_bookkeeping": False,
        },
    }


def build_placeholders(d: dict) -> dict:
    """Build a starter placeholders.yaml stub.

    Customer fills these in via alpen-customize.py or the SKILL.
    Stub provides the structure + a few obvious defaults from collected data.
    """
    return {
        "schema_version": "0.1",
        "tenant": d["tenant_id"],
        "last_updated": date.today().isoformat(),
        "upstream": {
            # 46 known upstream placeholders — fill the obvious ones
            "email": "Gmail",
            "calendar": "Google Calendar",
            "drive": "Google Drive",
            "office": "Google Workspace",
            "user": d["principal_name"],
            "AI": "Claude Code (Sonnet/Haiku/Opus 4.X)",
            # Leave the rest empty for the customer to fill
            "chat": "", "meeting": "", "conversation": "",
            "task": "", "Task": "", "notebook": "", "knowledge": "",
            "source": "", "CI": "", "cloud": "", "data": "", "monitoring": "",
            "CRM": "", "sales": "", "marketing": "", "competitive": "",
            "analytics": "", "SEO": "", "support": "",
            "CLM": "", "e-signature": "", "project": "", "Jira": "",
            "design": "", "product": "",
            "scientific": "", "literature": "", "journal": "",
            "lab": "", "clinical": "", "chemical": "", "drug": "", "genomics": "",
            "ITSM": "", "incident": "", "procurement": "", "erp": "",
            "category": "", "tool": "",
            "your-org-channel": "", "your-team-channel": "",
        },
        "alpen_extensions": {
            # Tier ladder — populate from collected entity data, blank otherwise
            "alpen-principal-name":  d["principal_name"],
            "alpen-principal-email": d["principal_email"],
            "alpen-vault-path":      d["vault_path"],
            "alpen-state-dir":       d["state_dir"],
            "alpen-log-dir":         d["log_dir"],
            # Entity tier names — placeholder pending business-model config
            "alpen-tier-1-name": "",
            "alpen-tier-2-name": "",
            "alpen-tier-3-name": "",
            "alpen-tier-1-fee":  "",
            "alpen-tier-2-fee":  "",
            "alpen-tier-3-fee":  "",
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────────────────

class _NoAliasDumper(yaml.SafeDumper):
    """Avoid YAML anchor/alias output; produce flat readable YAML."""
    def ignore_aliases(self, data):
        return True


def dump_yaml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.dump(data, f, Dumper=_NoAliasDumper, sort_keys=False, default_flow_style=False)


# ──────────────────────────────────────────────────────────────────────────────
# Validation hook
# ──────────────────────────────────────────────────────────────────────────────

def run_validator(tenant_id: str) -> int:
    import subprocess
    py = PLATFORM_ROOT / ".venv" / "bin" / "python"
    if not py.is_file():
        py = "python3"
    validator = PLATFORM_ROOT / "bin" / "validate-tenant-config.py"
    return subprocess.call([str(py), str(validator), "--tenant", tenant_id])


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, help="lowercase kebab-case slug")
    parser.add_argument("--from-args", action="store_true", help="non-interactive; require all fields via flags")
    parser.add_argument("--force", action="store_true", help="overwrite existing tenant dir")

    # Scripted-mode flags (ignored in interactive mode)
    parser.add_argument("--tenant-name")
    parser.add_argument("--tenant-type", default="general-consulting")
    parser.add_argument("--timezone", default="America/New_York")
    parser.add_argument("--locale", default="en-US")
    parser.add_argument("--vault-path")
    parser.add_argument("--state-dir", default="~/.local/state/alpen")
    parser.add_argument("--log-dir", default="~/Library/Logs/alpen")
    parser.add_argument("--principal-id")
    parser.add_argument("--principal-name")
    parser.add_argument("--principal-email")
    parser.add_argument("--entity-id")
    parser.add_argument("--entity-name")
    parser.add_argument("--entity-type")
    parser.add_argument("--entity-domain")

    args = parser.parse_args()

    tenant_dir = TENANTS_DIR / args.tenant_id
    if tenant_dir.exists() and not args.force:
        sys.exit(f"error: tenant dir already exists: {tenant_dir}\n        pass --force to overwrite")

    if args.from_args:
        required = ["tenant_name", "principal_name", "principal_email",
                    "entity_id", "entity_name", "entity_type"]
        missing = [r for r in required if not getattr(args, r)]
        if missing:
            sys.exit(f"error: --from-args requires: {', '.join('--' + r.replace('_', '-') for r in missing)}")
        data = collect_from_args(args)
    else:
        data = collect_interactive(args.tenant_id)

    # Build artifacts
    config = build_config(data)
    placeholders = build_placeholders(data)

    # Write
    config_path = tenant_dir / "config.yaml"
    placeholders_path = tenant_dir / "placeholders.yaml"
    dump_yaml(config, config_path)
    dump_yaml(placeholders, placeholders_path)

    print()
    print(f"=== Tenant '{args.tenant_id}' bootstrapped ===")
    print(f"  config:       {config_path}")
    print(f"  placeholders: {placeholders_path}")
    print()
    print("=== Validating ===")
    rc = run_validator(args.tenant_id)
    if rc != 0:
        print("\n!! validation failed; review the errors above and edit the files manually !!")
        return rc

    print()
    print("=== Next steps ===")
    print(f"  1. Review the generated files:")
    print(f"     - {config_path}")
    print(f"     - {placeholders_path}")
    print(f"  2. Fill in the empty placeholder values per your stack:")
    print(f"     bin/alpen-customize.py --plugin <plugin-name> --tenant {args.tenant_id} --dry-run")
    print(f"  3. Customize entity-specific templates:")
    print(f"     mkdir -p templates/{data['entity_id']}/")
    print(f"     # copy + edit templates/default/*.md as needed")
    print(f"  4. Run regenerators when you have data to index:")
    print(f"     bin/regenerate-leads-index.py --tenant {args.tenant_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
