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
SQLITE_DIR = Path(os.path.expanduser("~/.local/state/alpen/sqlite"))
HFO_LOG = Path(os.path.expanduser("~/Winnie/bin/hfo-log"))


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

def init_db(name: str) -> Path:
    """Drop + recreate the SQLite DB at ~/.local/state/alpen/sqlite/<name>.db
    from the schema at schemas/sql/<name>.sql. Returns the DB path."""
    SQLITE_DIR.mkdir(parents=True, exist_ok=True)
    db_path = SQLITE_DIR / f"{name}.db"
    schema_path = SCHEMAS_DIR / f"{name}.sql"
    if not schema_path.is_file():
        sys.exit(f"error: schema not found at {schema_path}")
    if db_path.exists():
        # Backup the existing DB to .prev before rebuild
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
