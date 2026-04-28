#!/usr/bin/env python3
"""Extract Voice-of-Customer signals from Plaud meeting transcripts.

Calls Claude (via the user's Max-subscription claude CLI) with a structured
extraction prompt per transcript and persists signals to voc-signals.db.

Heuristic for selecting transcripts: any markdown file under
${VAULT}/**/Plaud-Recordings/*.md with frontmatter type=plaud-recording
and transcript_status=full. Per-tenant config drives the vault root.

Per feedback_alpen_storage_patterns.md: SQLite at ~/.local/state/alpen/sqlite/.
Per feedback_alpen_instrumentation_patterns.md: emits script_completed via hfo-log.

Usage:
  voc-extract.py --tenant phil-howard --transcript <path>
  voc-extract.py --tenant phil-howard --backfill              # all unprocessed
  voc-extract.py --tenant phil-howard --backfill --since 2026-04-01
  voc-extract.py --tenant phil-howard --transcript <path> --re-extract
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = PLATFORM_ROOT / "schemas" / "sql"
SQLITE_DIR = Path(os.path.expanduser("~/.local/state/alpen/sqlite"))
VOC_DB = SQLITE_DIR / "voc-signals.db"
SCRIPT_NAME = "voc-extract"
EXTRACTOR_VERSION = "v0.1"


def init_db() -> None:
    SQLITE_DIR.mkdir(parents=True, exist_ok=True)
    if VOC_DB.exists():
        return  # don't drop existing data; voc-signals are accumulated, not regenerated
    conn = sqlite3.connect(VOC_DB)
    with (SCHEMAS_DIR / "voc-signals.sql").open() as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    try:
        fm = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, text[end + 5:]


def entity_from_path(vault_path: Path, vault_root: Path) -> str | None:
    """First path segment under vault_root indicates the entity area."""
    try:
        rel = vault_path.relative_to(vault_root)
        first = rel.parts[0]
    except (ValueError, IndexError):
        return None
    return {
        "Cognitive-Capital-Group": "ccg",
        "Alpen-Tech": "alpen-tech",
        "Kroger": "kroger",
        "Personal": "personal",
        "Plaud-Recordings": "personal",  # top-level Plaud-Recordings = uncategorized = personal default
    }.get(first)


def find_transcripts(vault_root: Path, since: date | None = None) -> list[Path]:
    out = []
    for area in ("Cognitive-Capital-Group", "Alpen-Tech", "Kroger", "Personal", "Plaud-Recordings"):
        d = vault_root / area / "Plaud-Recordings" if area != "Plaud-Recordings" else vault_root / area
        if not d.is_dir():
            continue
        for f in d.glob("*.md"):
            if f.name.startswith(".") or f.name.startswith("_"):
                continue
            text = f.read_text(errors="replace")
            fm, _ = split_frontmatter(text)
            if fm.get("type") != "plaud-recording":
                continue
            if fm.get("transcript_status") != "full":
                continue
            d_ = fm.get("date")
            if since and d_ and isinstance(d_, date) and d_ < since:
                continue
            out.append(f)
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def transcript_already_extracted(conn: sqlite3.Connection, slug: str) -> str | None:
    row = conn.execute(
        "SELECT extractor_version FROM transcript WHERE id = ?", (slug,)
    ).fetchone()
    return row[0] if row else None


EXTRACTION_PROMPT = """You are extracting Voice-of-Customer (VoC) signals from a meeting transcript.

The signals you extract will drive sales/CS/product workflows. Be CONSERVATIVE: only extract signals that are clearly supported by the text. False positives are worse than false negatives.

Categories and their meanings:

- expansion: account expressed interest in scope beyond what's currently sold
- objection: pushback, skepticism, or specific reservation about an offering
- churn_risk: any indicator the relationship is at risk (delays, frustration, exit signals)
- feedback: product/service feedback worth forwarding to product team
- competitive: mention of a competitor or comparison to an alternative
- expansion_blocker: a specific gap that, if closed, would unlock more business
- commitment: a verbal commitment from a stakeholder (timeline, action, decision)
- ask: a specific request from a stakeholder (info, demo, intro, etc.)
- praise: explicit positive feedback worth celebrating
- risk: engagement-level risk (Delivery dept concern)
- opportunity: a general opportunity that doesn't fit cleanly above

Severity levels: low | medium | high | critical
- critical: needs response within 24 hours OR represents 6-figure+ value
- high: needs response within a week, or material to a deal in flight
- medium: worth tracking but not time-sensitive
- low: signal noise, or minor / soft

Topic: one short string naming the section / theme this signal came from.

Account attribution: name the specific account/company this signal is about (use empty string if internal/N/A).

Output ONE JSON ARRAY ONLY (no preamble, no markdown). Maximum 12 signals per transcript. Each item:

  {
    "signal_type": "<one of the categories>",
    "severity": "<low|medium|high|critical>",
    "description": "<one-sentence summary, max 240 chars>",
    "evidence": "<a verbatim or near-verbatim quote from the transcript, max 400 chars>",
    "topic": "<the section / theme, max 60 chars>",
    "attributed_to_account": "<account name or empty string>"
  }

If the transcript contains no genuine signals, return [].
"""


def extract_signals_via_claude(transcript_text: str, max_chars: int = 60000) -> list[dict] | None:
    """Run claude -p with the extraction prompt; return parsed JSON list (or None on error)."""
    # Truncate massive transcripts; the AI Summary is usually at the top so the front 60K is enough
    body = transcript_text[:max_chars]
    full_prompt = f"{EXTRACTION_PROMPT}\n\n--- TRANSCRIPT ---\n{body}\n--- END ---\n\nReturn the JSON array now."

    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--settings", str(Path.home() / "Winnie" / "config" / "scheduled.settings.json"),
                "--dangerously-skip-permissions",
                full_prompt,
            ],
            capture_output=True, text=True, timeout=180, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  ! claude CLI failed: {e}", file=sys.stderr)
        return None

    if result.returncode != 0:
        print(f"  ! claude exit {result.returncode}: {result.stderr[:200]}", file=sys.stderr)
        return None

    output = result.stdout.strip()
    # Strip a leading "no stdin" warning if present
    output = re.sub(r"^Warning: no stdin.*?\n", "", output, count=1)

    # Extract a JSON array — handle both bare array and array inside a code fence
    m = re.search(r"\[[\s\S]*\]", output)
    if not m:
        print(f"  ! no JSON array in output: {output[:200]}", file=sys.stderr)
        return None
    try:
        signals = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"  ! JSON parse error: {e}", file=sys.stderr)
        return None
    if not isinstance(signals, list):
        return None
    return signals


def best_guess_client_name(fm: dict, body: str) -> str | None:
    """Heuristic: look for capitalized account names in title or first 500 chars of body."""
    title = (fm.get("title") or "")
    candidates = re.findall(r"\b(WebMD|Roche|Eli Lilly|Apple|Calm Health|Dallas Chamber|Brain Capital|MD Anderson|Slalom|McKinsey|Optum|UT Dallas|Harvard|Mercer|MLS|Compassion 2\.0|Blue Ash|Kroger|InnoSync|TASI|Kenvue|BP|Center for Brain Health|CBH)\b", title + " " + body[:500])
    if candidates:
        return candidates[0]
    return None


def insert_transcript_and_signals(conn: sqlite3.Connection, slug: str, vault_path: str,
                                   tenant_id: str, entity_id: str | None, fm: dict,
                                   client_name: str | None, signals: list[dict]) -> int:
    # Replace any prior extraction for idempotent re-extraction
    conn.execute("DELETE FROM transcript WHERE id = ?", (slug,))
    conn.execute("""
        INSERT INTO transcript (id, tenant_id, entity_id, vault_path, meeting_date,
                                meeting_title, duration_text, lead_id, client_name,
                                extractor_version, signal_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        slug, tenant_id, entity_id, vault_path,
        fm.get("date").isoformat() if isinstance(fm.get("date"), date) else fm.get("date"),
        fm.get("title"),
        fm.get("duration"),
        None,  # lead_id — set later by reconciler that joins to leads.db on client_name
        client_name,
        EXTRACTOR_VERSION,
        len(signals),
    ))
    valid_types = {
        "expansion", "objection", "churn_risk", "feedback", "competitive",
        "expansion_blocker", "commitment", "ask", "praise", "risk", "opportunity",
    }
    valid_sev = {"low", "medium", "high", "critical"}
    inserted = 0
    for s in signals:
        if not isinstance(s, dict):
            continue
        st = (s.get("signal_type") or "").strip()
        sev = (s.get("severity") or "medium").strip().lower()
        if st not in valid_types or sev not in valid_sev:
            continue
        try:
            conn.execute("""
                INSERT INTO signal (transcript_id, signal_type, severity, description, evidence,
                                    topic, attributed_to_account)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                slug, st, sev,
                (s.get("description") or "")[:240],
                (s.get("evidence") or "")[:1200],
                (s.get("topic") or "")[:60],
                (s.get("attributed_to_account") or None) or None,
            ))
            inserted += 1
        except sqlite3.Error as e:
            print(f"    ! signal insert skipped: {e}", file=sys.stderr)
    conn.execute("UPDATE transcript SET signal_count = ? WHERE id = ?", (inserted, slug))
    conn.commit()
    return inserted


def process_transcript(conn: sqlite3.Connection, path: Path, vault_root: Path, tenant_id: str,
                       re_extract: bool) -> tuple[bool, int]:
    slug = path.stem
    text = path.read_text(errors="replace")
    fm, body = split_frontmatter(text)

    if not re_extract and transcript_already_extracted(conn, slug) == EXTRACTOR_VERSION:
        return False, 0

    print(f"  > {slug}")
    entity = entity_from_path(path, vault_root)
    client = best_guess_client_name(fm, body)
    signals = extract_signals_via_claude(text)
    if signals is None:
        return False, 0

    rel_path = str(path.relative_to(vault_root)) if vault_root in path.parents else str(path)
    n = insert_transcript_and_signals(conn, slug, rel_path, tenant_id, entity, fm, client, signals)
    print(f"      → {n} signal(s); entity={entity}; client={client or '—'}")
    return True, n


def load_tenant_vault(tenant_id: str) -> Path:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    if not p.is_file():
        sys.exit(f"error: tenant config not found: {p}")
    with p.open() as f:
        cfg = yaml.safe_load(f) or {}
    return Path(os.path.expanduser(cfg["tenant"]["vault_path"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--transcript", help="Path to a single transcript file")
    parser.add_argument("--backfill", action="store_true", help="Process all unprocessed transcripts")
    parser.add_argument("--since", help="Only consider transcripts dated >= YYYY-MM-DD")
    parser.add_argument("--re-extract", action="store_true", help="Re-process even if already in DB")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N transcripts (for testing)")
    args = parser.parse_args()

    if not (args.transcript or args.backfill):
        sys.exit("error: pass --transcript <path> or --backfill")

    init_db()
    vault_root = load_tenant_vault(args.tenant)

    targets: list[Path] = []
    if args.transcript:
        p = Path(args.transcript).expanduser()
        if not p.is_file():
            sys.exit(f"error: not a file: {p}")
        targets = [p]
    else:
        since = date.fromisoformat(args.since) if args.since else None
        targets = find_transcripts(vault_root, since=since)
        if args.limit:
            targets = targets[: args.limit]

    print(f"=== voc-extract (tenant={args.tenant}) ===")
    print(f"vault:    {vault_root}")
    print(f"targets:  {len(targets)}")
    print()

    start = time.time()
    conn = sqlite3.connect(VOC_DB)
    extracted, signal_total, errors = 0, 0, 0
    for path in targets:
        try:
            ok, n = process_transcript(conn, path, vault_root, args.tenant, args.re_extract)
        except Exception as e:
            print(f"  ! {path.stem}: {type(e).__name__}: {e}", file=sys.stderr)
            errors += 1
            continue
        if ok:
            extracted += 1
            signal_total += n
    conn.close()

    elapsed = time.time() - start
    print()
    print(f"=== voc-extract complete in {elapsed:.1f}s ===")
    print(f"  transcripts processed: {extracted}")
    print(f"  signals captured:      {signal_total}")
    print(f"  errors:                {errors}")

    emit_telemetry(SCRIPT_NAME, outcome=("success" if errors == 0 else "partial_failure"),
                   transcripts_processed=extracted,
                   signals_captured=signal_total,
                   errors=errors,
                   duration_seconds=round(elapsed, 1))
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
