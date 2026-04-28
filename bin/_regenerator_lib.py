"""Shared utilities for the alpen-platform regenerator scripts.

Each regenerator (leads / contracts / engagements) reads per-record markdown
files from a vault directory, parses YAML frontmatter, and writes to a
SQLite DB at ~/.local/state/alpen/sqlite/<name>.db.

Per feedback_alpen_storage_patterns.md:
- Markdown is truth, SQLite is regenerable index
- Single-writer per DB
- Never on iCloud / Google Drive (path is local)

Per feedback_alpen_instrumentation_patterns.md:
- Each regenerator emits a `script_completed` event via hfo-log
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

# ──────────────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────────────

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = PLATFORM_ROOT / "schemas" / "sql"
DEFAULT_SQLITE_DIR = Path(os.path.expanduser("~/.local/state/alpen/sqlite"))
HFO_LOG = Path(os.path.expanduser("~/Winnie/bin/hfo-log"))


def tenant_state_dir(tenant_id: str | None) -> Path:
    """Resolve the SQLite state directory for a given tenant.

    Reads tenants/<id>/config.yaml for `tenant.state_dir`; appends '/sqlite'.
    Falls back to ~/.local/state/alpen/sqlite/ when:
      - tenant_id is None
      - tenant config doesn't exist
      - state_dir field absent

    This is the multi-tenant safety net: running regenerator with
    --tenant <other> resolves to <other>'s state dir, NOT the default
    shared one. Prevents data pollution across tenants on the same host.
    """
    if not tenant_id:
        return DEFAULT_SQLITE_DIR
    cfg_path = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    if not cfg_path.is_file():
        return DEFAULT_SQLITE_DIR
    try:
        with cfg_path.open() as f:
            cfg = yaml.safe_load(f) or {}
        sd = (cfg.get("tenant") or {}).get("state_dir")
        if not sd:
            return DEFAULT_SQLITE_DIR
        return Path(os.path.expanduser(sd)) / "sqlite"
    except Exception:
        return DEFAULT_SQLITE_DIR


# ──────────────────────────────────────────────────────────────────────────────
# Frontmatter parsing
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ParsedRecord:
    slug: str
    fm: dict
    body: str
    path: Path


def parse_record(path: Path) -> ParsedRecord | None:
    """Parse a per-record markdown file into a ParsedRecord. Returns None on
    failure (logged, but caller continues with other records)."""
    try:
        text = path.read_text()
    except Exception as e:
        print(f"  ! could not read {path.name}: {e}", file=sys.stderr)
        return None
    if not text.startswith("---\n"):
        print(f"  ! no frontmatter in {path.name}", file=sys.stderr)
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        print(f"  ! malformed frontmatter in {path.name}", file=sys.stderr)
        return None
    try:
        fm = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as e:
        print(f"  ! YAML error in {path.name}: {e}", file=sys.stderr)
        return None
    body = text[end + 5:]
    return ParsedRecord(slug=path.stem, fm=fm, body=body, path=path)


def find_records(source_dir: Path) -> list[ParsedRecord]:
    """Find every .md file in source_dir (non-recursive), excluding _index.md
    and hidden files. Returns list of ParsedRecord (skipping unparseable)."""
    if not source_dir.is_dir():
        return []
    records = []
    for path in sorted(source_dir.glob("*.md")):
        if path.stem.startswith("_") or path.stem.startswith("."):
            continue
        rec = parse_record(path)
        if rec is not None:
            records.append(rec)
    return records


# ──────────────────────────────────────────────────────────────────────────────
# DB initialization
# ──────────────────────────────────────────────────────────────────────────────

def init_db(name: str, tenant_id: str | None = None) -> Path:
    """Drop + recreate the SQLite DB at <tenant.state_dir>/sqlite/<name>.db.

    If tenant_id is provided, resolves the state dir from tenant config.
    Falls back to ~/.local/state/alpen/sqlite/ when no tenant given. This
    is the multi-tenant safety net — see tenant_state_dir() above.

    Schema source: schemas/sql/<name>.sql.
    Returns the DB path."""
    sqlite_dir = tenant_state_dir(tenant_id)
    sqlite_dir.mkdir(parents=True, exist_ok=True)
    db_path = sqlite_dir / f"{name}.db"
    schema_path = SCHEMAS_DIR / f"{name}.sql"
    if not schema_path.is_file():
        sys.exit(f"error: schema not found at {schema_path}")
    if db_path.exists():
        backup = db_path.with_suffix(".db.prev")
        shutil.copy2(db_path, backup)
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    with schema_path.open() as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    return db_path


# ──────────────────────────────────────────────────────────────────────────────
# Value parsers (markdown frontmatter is permissive; coerce safely)
# ──────────────────────────────────────────────────────────────────────────────

VALUE_RE = re.compile(r"\$?([\d,]+(?:\.\d+)?)")


def parse_money(raw) -> int | None:
    """Coerce '$500,000' or '500000' or '$30,000-$80,000' to int (USD).
    For ranges, returns the midpoint."""
    if raw is None or raw == "" or raw == "TBD" or raw == "—":
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw).strip()
    matches = VALUE_RE.findall(s)
    if not matches:
        return None
    try:
        nums = [int(float(m.replace(",", ""))) for m in matches]
    except ValueError:
        return None
    if len(nums) == 1:
        return nums[0]
    return (nums[0] + nums[-1]) // 2


def parse_money_range(raw) -> tuple[int | None, int | None]:
    """Coerce '$30,000-$80,000' to (30000, 80000). Single value -> (n, n).
    Empty -> (None, None)."""
    if raw is None or raw == "" or raw == "TBD" or raw == "—":
        return (None, None)
    if isinstance(raw, (int, float)):
        n = int(raw)
        return (n, n)
    matches = VALUE_RE.findall(str(raw))
    if not matches:
        return (None, None)
    try:
        nums = [int(float(m.replace(",", ""))) for m in matches]
    except ValueError:
        return (None, None)
    if len(nums) == 1:
        return (nums[0], nums[0])
    return (nums[0], nums[-1])


def coerce_date(raw) -> str | None:
    """Pass through ISO dates; coerce datetime objects; reject obvious junk."""
    if raw is None or raw == "" or raw == "TBD":
        return None
    if hasattr(raw, "strftime"):  # date or datetime
        return raw.strftime("%Y-%m-%d")
    s = str(raw).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    return None


def coerce_str(raw) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def coerce_int(raw) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Signatory resolution (used by all composer scripts)
# ──────────────────────────────────────────────────────────────────────────────

def build_signatory_context(tenant_cfg: dict, entity_id: str,
                             signatory_override: str | None = None) -> dict:
    """Build the {principal_*, partner_*, signatory_*} block for tenant context.

    - principal_*: the role=ceo principal (Phil), with their entity-specific title
                   (e.g. 'Chief Operating Officer' at CCG, 'Chief Executive Officer' at Alpen Tech)
    - partner_*:   the role=partner principal (Krystal), with their entity-specific title
                   (e.g. 'Chief Executive Officer' at CCG; falls back to 'Partner' if
                   not authorized at the entity)
    - signatory_*: whoever find_signatory resolved (Krystal for CCG default; Phil for Alpen)

    Templates' SIGNATURE BLOCKS use {{tenant.signatory_*}}.
    Templates' BODY REFERENCES (e.g., 'Krystal is the lead investigator') keep
    using {{tenant.partner_*}} or {{tenant.principal_*}} as static role labels.
    """
    entity = next((e for e in tenant_cfg.get("entities") or [] if e.get("id") == entity_id), {})
    sigs = entity.get("signatories") or []
    title_by_principal = {s["principal_id"]: s["title"] for s in sigs}

    ceo = next((p for p in tenant_cfg.get("principals") or [] if p.get("role") == "ceo"), {})
    partner = next((p for p in tenant_cfg.get("principals") or [] if p.get("role") == "partner"), {})

    signatory, signatory_title = find_signatory(tenant_cfg, entity_id, signatory_override)

    def email_of(p: dict) -> str:
        return (p.get("accounts") or [{}])[0].get("address", "TBD") if p else "TBD"

    return {
        "principal_name":  ceo.get("name", "TBD"),
        "principal_title": title_by_principal.get(ceo.get("id", ""), "Chief Executive Officer"),
        "principal_email": email_of(ceo),
        "partner_name":  partner.get("name", "TBD") if partner else "TBD",
        "partner_title": title_by_principal.get(partner.get("id", ""), "Partner") if partner else "TBD",
        "partner_email": email_of(partner) if partner else "TBD",
        "signatory_name":  signatory["name"],
        "signatory_title": signatory_title,
        "signatory_email": email_of(signatory),
    }


def find_signatory(tenant_cfg: dict, entity_id: str, override_principal_id: str | None = None) -> tuple[dict, str]:
    """Resolve which principal signs for the given entity, with what title.

    Args:
      tenant_cfg: parsed tenant config (full config.yaml contents)
      entity_id: entity to look up signatories under
      override_principal_id: if set, use this principal (must be authorized for the entity)

    Returns (principal_dict, title_string).

    Raises SystemExit if:
      - entity not in config
      - override principal not authorized for entity
    """
    entity = next((e for e in tenant_cfg.get("entities") or [] if e.get("id") == entity_id), None)
    if not entity:
        sys.exit(f"error: entity {entity_id!r} not in tenant config")
    sigs = entity.get("signatories") or []

    # No signatories declared — fall back to first principal as legacy default
    if not sigs:
        principals = tenant_cfg.get("principals") or []
        if not principals:
            sys.exit(f"error: entity {entity_id!r} has no signatories and no principals to fall back to")
        return principals[0], "Authorized Representative"

    # Pick the requested signatory or the entity's default
    if override_principal_id:
        match = next((s for s in sigs if s.get("principal_id") == override_principal_id), None)
        if not match:
            authorized = ", ".join(s.get("principal_id") for s in sigs)
            sys.exit(f"error: principal {override_principal_id!r} not authorized to sign for entity {entity_id!r}; authorized: {authorized}")
    else:
        match = next((s for s in sigs if s.get("default")), sigs[0])

    principal = next((p for p in tenant_cfg.get("principals") or [] if p.get("id") == match["principal_id"]), None)
    if not principal:
        sys.exit(f"error: principal {match['principal_id']!r} declared as signatory for {entity_id!r} but not found in tenant.principals")

    return principal, match["title"]


# ──────────────────────────────────────────────────────────────────────────────
# Telemetry
# ──────────────────────────────────────────────────────────────────────────────

def emit_telemetry(script_name: str, *, outcome: str, **metrics) -> None:
    """Emit a script_completed event via hfo-log. Silent on failure
    (telemetry never blocks real work).

    hfo-log uses --key value (not key=value); converts underscores in metric
    keys to hyphens for consistency with the established CLI convention."""
    if not HFO_LOG.is_file():
        return
    args: list[str] = [
        str(HFO_LOG),
        "--script", script_name,
        "--event", "script_completed",
        "--outcome", outcome,
    ]
    for k, v in metrics.items():
        flag = "--" + k.replace("_", "-")
        args.extend([flag, str(v)])
    try:
        subprocess.run(args, check=False, capture_output=True, timeout=5)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Run helpers
# ──────────────────────────────────────────────────────────────────────────────

class Run:
    """Context for one regenerator run. Tracks counts + duration."""

    def __init__(self, script_name: str):
        self.script_name = script_name
        self.start = time.time()
        self.records_seen = 0
        self.records_inserted = 0
        self.records_skipped = 0
        self.errors: list[str] = []

    def report(self, db_path: Path) -> None:
        elapsed = time.time() - self.start
        print()
        print(f"=== {self.script_name} complete in {elapsed:.2f}s ===")
        print(f"  records seen:     {self.records_seen}")
        print(f"  records inserted: {self.records_inserted}")
        print(f"  records skipped:  {self.records_skipped}")
        print(f"  errors:           {len(self.errors)}")
        for e in self.errors[:5]:
            print(f"    - {e}")
        print(f"  output db:        {db_path}")
        outcome = "success" if not self.errors else "partial_failure"
        emit_telemetry(
            self.script_name,
            outcome=outcome,
            records_seen=self.records_seen,
            records_inserted=self.records_inserted,
            records_skipped=self.records_skipped,
            error_count=len(self.errors),
            duration_seconds=round(elapsed, 2),
        )
