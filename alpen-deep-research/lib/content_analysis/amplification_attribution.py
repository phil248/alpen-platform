#!/usr/bin/env python3
"""Compute amplification attribution (external_outlet x cbh_person x programs).

Single callable entry point: ``compute_amplification_attribution(
inventory_root, output_csv_path, output_md_path)``. Replaces the inline-Bash
+ Haiku-NER prose previously expected of agents.

The script iterates ``<inventory_root>/amplifications/*.json``, locates a
matching v2 transcript (falling back to v1) under
``<inventory_root>/_assets/transcripts/<slug>*.html-extracted-v{2,1}.md``,
calls the local ``claude`` CLI with ``--model haiku`` and a strict-JSON
prompt, parses the response, updates the amplification JSON in-place, and
writes the CSV + MD aggregates.

Idempotent at the deliverable level (CSV/MD overwrite atomically); the
amplification JSON updates are also idempotent because the same NER output
is regenerated from the same transcript text.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NER_PROMPT_TEMPLATE = """You are an information-extraction tool. From the article body below, extract:
- external_outlet: the publishing outlet name (e.g., "The New York Times", "Dallas Morning News"). Null if the body is the outlet's own newsroom.
- cbh_person_byline: full name of any Center for BrainHealth (CBH) person quoted, bylined, or featured (e.g., "Sandra Bond Chapman", "Ian Robertson"). Null if none.
- cbh_programs_referenced: list of CBH program names mentioned (e.g., ["SMART", "BrainHealth Project"]). Empty list if none.

Return STRICT JSON ONLY, no prose, matching this exact shape:
{"external_outlet": <string|null>, "cbh_person_byline": <string|null>, "cbh_programs_referenced": [<string>, ...]}

ARTICLE BODY (truncated):
---
{body}
---
"""

BODY_CHAR_LIMIT = 12_000  # keep prompts well under context budget
CLAUDE_TIMEOUT_S = 90


def _find_transcript(inventory_root: Path, slug: str) -> Path | None:
    transcripts = inventory_root / "_assets" / "transcripts"
    if not transcripts.is_dir():
        return None
    # Prefer v2 over v1.
    for suffix in ("-v2.md", "-v1.md", ".md"):
        for path in sorted(transcripts.glob(f"{slug}*.html-extracted{suffix}")):
            if path.is_file():
                return path
    # Fallback: any extracted file starting with the slug.
    for path in sorted(transcripts.glob(f"{slug}*-extracted*.md")):
        if path.is_file():
            return path
    return None


def _run_haiku_ner(body: str, claude_bin: str) -> dict[str, Any] | None:
    prompt = NER_PROMPT_TEMPLATE.replace("{body}", body[:BODY_CHAR_LIMIT])
    try:
        proc = subprocess.run(
            [
                claude_bin,
                "-p",
                "--model",
                "haiku",
                "--output-format",
                "text",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or "").strip()
    if not text:
        return None
    # Strip markdown fences if model wrapped JSON.
    if text.startswith("```"):
        text = text.strip("`")
        # remove leading "json\n"
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
        text = text.strip("`").strip()
    # Find first { and last } to be tolerant of preface/postface.
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or last < first:
        return None
    try:
        parsed = json.loads(text[first : last + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    # Normalize fields.
    outlet = parsed.get("external_outlet")
    person = parsed.get("cbh_person_byline")
    programs = parsed.get("cbh_programs_referenced") or []
    if not isinstance(programs, list):
        programs = []
    return {
        "external_outlet": outlet if isinstance(outlet, str) else None,
        "cbh_person_byline": person if isinstance(person, str) else None,
        "cbh_programs_referenced": [
            p for p in programs if isinstance(p, str) and p.strip()
        ],
    }


def _atomic_write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def _is_chain_complete(rec: dict[str, Any]) -> bool:
    return bool(
        rec.get("amplified_external_outlet")
        and rec.get("cbh_person_byline")
        and rec.get("cbh_programs_referenced")
    )


def compute_amplification_attribution(
    inventory_root: str,
    output_csv_path: str,
    output_md_path: str,
    claude_bin: str | None = None,
    skip_ner: bool = False,
) -> dict[str, Any]:
    """For each amplification entity, NER-extract attribution chain.

    Args:
        inventory_root: Absolute path to per-client inventory root.
        output_csv_path: Absolute path for the CSV deliverable.
        output_md_path: Absolute path for the MD rollup.
        claude_bin: Path to ``claude`` binary; auto-resolved via ``which``
            when None.
        skip_ner: When True, skip the LLM NER pass and only aggregate
            existing fields on the records (useful for offline testing).

    Returns:
        Dict with keys ``records``, ``complete_chains``, ``by_outlet``,
        ``by_person``.
    """
    root = Path(inventory_root)
    amp_dir = root / "amplifications"
    if not amp_dir.is_dir():
        return {"records": 0, "complete_chains": 0, "by_outlet": {}, "by_person": {}}

    resolved_claude = claude_bin or shutil.which("claude") or "/opt/homebrew/bin/claude"

    rows: list[dict[str, Any]] = []
    by_outlet: Counter[str] = Counter()
    by_person: Counter[str] = Counter()
    by_program: Counter[str] = Counter()
    complete = 0

    for jf in sorted(amp_dir.glob("*.json")):
        try:
            with jf.open("r", encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rec, dict):
            continue

        slug = jf.stem
        transcript = _find_transcript(root, slug)
        ner_applied = False
        if not skip_ner and transcript is not None:
            try:
                body = transcript.read_text(encoding="utf-8", errors="replace")
            except OSError:
                body = ""
            if body.strip():
                ner = _run_haiku_ner(body, resolved_claude)
                if ner is not None:
                    # Only fill missing fields; don't overwrite curator-set
                    # values unless they are empty.
                    if ner.get("external_outlet") and not rec.get(
                        "amplified_external_outlet"
                    ):
                        rec["amplified_external_outlet"] = ner["external_outlet"]
                    if ner.get("cbh_person_byline") and not rec.get("cbh_person_byline"):
                        rec["cbh_person_byline"] = ner["cbh_person_byline"]
                    if ner.get("cbh_programs_referenced") and not rec.get(
                        "cbh_programs_referenced"
                    ):
                        rec["cbh_programs_referenced"] = ner["cbh_programs_referenced"]
                    rec["nlp_attribution_run_id"] = (
                        f"amp-attr-{datetime.now(timezone.utc):%Y-%m-%dT%H%M%SZ}"
                    )
                    _atomic_write_json(jf, rec)
                    ner_applied = True

        outlet = rec.get("amplified_external_outlet") or ""
        person = rec.get("cbh_person_byline") or ""
        programs = rec.get("cbh_programs_referenced") or []
        if not isinstance(programs, list):
            programs = []

        if _is_chain_complete(rec):
            complete += 1
        if outlet:
            by_outlet[outlet] += 1
        if person:
            by_person[person] += 1
        for p in programs:
            if isinstance(p, str) and p.strip():
                by_program[p] += 1

        rows.append(
            {
                "slug": slug,
                "title": rec.get("title", ""),
                "url": rec.get("url", ""),
                "external_outlet": outlet,
                "cbh_person_byline": person,
                "cbh_programs_referenced": "; ".join(
                    p for p in programs if isinstance(p, str)
                ),
                "external_publication_date": rec.get("external_publication_date", ""),
                "transcript_local_path": rec.get("transcript_local_path", ""),
                "ner_applied": ner_applied,
            }
        )

    rows.sort(key=lambda r: (r["external_outlet"].lower(), r["slug"]))

    # Write CSV (atomic).
    csv_path = Path(output_csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_tmp = csv_path.with_suffix(csv_path.suffix + ".tmp")
    fieldnames = [
        "slug",
        "title",
        "url",
        "external_outlet",
        "cbh_person_byline",
        "cbh_programs_referenced",
        "external_publication_date",
        "transcript_local_path",
        "ner_applied",
    ]
    with csv_tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    csv_tmp.replace(csv_path)

    # Write Markdown rollup (atomic).
    md_path = Path(output_md_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []
    lines.append("# Amplification Attribution Rollup")
    lines.append("")
    lines.append(f"- Inventory root: `{root}`")
    lines.append(f"- Generated (UTC): {timestamp}")
    lines.append(f"- Records: {len(rows)}")
    lines.append(f"- Complete chains (outlet x person x program): {complete}")
    lines.append("")
    lines.append("## By outlet")
    lines.append("")
    lines.append("| Outlet | Count |")
    lines.append("|---|---:|")
    for outlet, count in by_outlet.most_common():
        lines.append(f"| {outlet} | {count} |")
    if not by_outlet:
        lines.append("| _(none)_ | 0 |")
    lines.append("")
    lines.append("## By CBH person")
    lines.append("")
    lines.append("| Person | Count |")
    lines.append("|---|---:|")
    for person, count in by_person.most_common():
        lines.append(f"| {person} | {count} |")
    if not by_person:
        lines.append("| _(none)_ | 0 |")
    lines.append("")
    lines.append("## By program")
    lines.append("")
    lines.append("| Program | Count |")
    lines.append("|---|---:|")
    for program, count in by_program.most_common():
        lines.append(f"| {program} | {count} |")
    if not by_program:
        lines.append("| _(none)_ | 0 |")
    lines.append("")
    md_tmp = md_path.with_suffix(md_path.suffix + ".tmp")
    md_tmp.write_text("\n".join(lines), encoding="utf-8")
    md_tmp.replace(md_path)

    return {
        "records": len(rows),
        "complete_chains": complete,
        "by_outlet": dict(by_outlet),
        "by_person": dict(by_person),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute amplification attribution rollup."
    )
    parser.add_argument(
        "--inventory-root",
        required=True,
        help="Absolute path to per-client inventory root",
    )
    parser.add_argument(
        "--output-csv", required=True, help="Absolute path for CSV deliverable"
    )
    parser.add_argument(
        "--output-md", required=True, help="Absolute path for MD rollup"
    )
    parser.add_argument(
        "--claude-bin", default=None, help="Path to claude CLI (default: which claude)"
    )
    parser.add_argument(
        "--skip-ner", action="store_true", help="Skip LLM NER (offline mode)"
    )
    args = parser.parse_args()

    result = compute_amplification_attribution(
        args.inventory_root,
        args.output_csv,
        args.output_md,
        claude_bin=args.claude_bin,
        skip_ner=args.skip_ner,
    )
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
