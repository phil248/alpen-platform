#!/usr/bin/env python3
"""Build a scope object from a discovery transcript or interactive Q&A.

Walks templates/default/scope-questionnaire.yaml. For each required field,
pre-fills from the discovery transcript (if provided) and a leads.db row
(if --lead-slug given), then asks the user for any unknowns.

Output:
  ${VAULT}/Solutions/Scopes/<lead-slug>.md  — human-readable scope doc
  /tmp/<slug>-scope.json                    — JSON deal context for compose-proposal

Optionally hands off to compose-proposal.py automatically.

Usage (interactive, with discovery transcript):
  scope-builder.py --tenant phil-howard --lead-slug eli-lilly --transcript path.md

Usage (interactive, no transcript, fully manual):
  scope-builder.py --tenant phil-howard --lead-slug eli-lilly

Usage (chained to compose-proposal):
  scope-builder.py --tenant phil-howard --lead-slug eli-lilly --compose --tier 2
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
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "scope-builder"
LEADS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/leads.db"))
QUESTIONNAIRE = PLATFORM_ROOT / "templates" / "default" / "scope-questionnaire.yaml"


def load_questionnaire(tenant_id: str, entity_id: str | None) -> dict:
    """Resolve scope-questionnaire.yaml: entity > tenant > default."""
    candidates = [
        PLATFORM_ROOT / "templates" / (entity_id or "_") / "scope-questionnaire.yaml",
        PLATFORM_ROOT / "templates" / tenant_id / "scope-questionnaire.yaml",
        QUESTIONNAIRE,
    ]
    for c in candidates:
        if c.is_file():
            with c.open() as f:
                return yaml.safe_load(f) or {}
    sys.exit(f"error: no questionnaire found")


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    if not p.is_file():
        sys.exit(f"error: tenant config not found: {p}")
    with p.open() as f:
        return yaml.safe_load(f) or {}


def load_lead(slug: str) -> dict | None:
    if not LEADS_DB.is_file():
        return None
    conn = sqlite3.connect(LEADS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM lead WHERE id = ?", (slug,)).fetchone()
    conn.close()
    return dict(row) if row else None


def evaluate_when(when: str | None, deal: dict) -> bool:
    """Evaluate the YAML 'when:' clause. Limited to safe expressions:
       deal.tier in [2, 3], deal.tier == 2, etc.
    Returns True if no when clause."""
    if not when:
        return True
    # Only allow whitelisted patterns
    safe_patterns = [
        (r"deal\.tier in \[(\d+(?:,\s*\d+)*)\]", lambda m: deal.get("tier") in [int(x.strip()) for x in m.group(1).split(",")]),
        (r"deal\.tier == (\d+)", lambda m: deal.get("tier") == int(m.group(1))),
    ]
    for pat, fn in safe_patterns:
        m = re.fullmatch(pat, when.strip())
        if m:
            return fn(m)
    print(f"  ! unrecognized when clause {when!r}; skipping section", file=sys.stderr)
    return False


def prefill_from_lead(lead: dict | None, deal: dict) -> int:
    """Pre-fill deal fields from a leads.db row. Returns count of fields filled."""
    if not lead:
        return 0
    n = 0
    if not deal.get("client_name") and lead.get("display_name"):
        deal["client_name"] = lead["display_name"]
        n += 1
    if not deal.get("client_company_name") and lead.get("company_name"):
        deal["client_company_name"] = lead["company_name"]
        n += 1
    if not deal.get("value") and lead.get("value_estimate"):
        deal["value"] = lead["value_estimate"]
        n += 1
    if not deal.get("tier") and lead.get("tier"):
        deal["tier"] = lead["tier"]
        n += 1
    if not deal.get("client_signatory_name") and lead.get("primary_contact"):
        deal["client_signatory_name"] = lead["primary_contact"]
        n += 1
    return n


SCOPE_EXTRACTION_PROMPT = """You are extracting scoping fields from a discovery-call transcript for a consulting engagement.

The output drives a proposal template. Be CONSERVATIVE: only fill a field if the
transcript clearly supports it. Empty / TBD beats hallucinated.

Return ONE JSON OBJECT ONLY (no preamble, no markdown). Fields (all optional):

{
  "client_name":        "<the client organization>",
  "industry":           "<their industry, one short phrase>",
  "headcount_range":    "<small <100 | mid 100-1000 | large 1000-10000 | enterprise 10000+>",
  "problem_statement":  "<one sentence: what the client is trying to solve>",
  "target_outcome":     "<one sentence: what they want at the end of the engagement>",
  "success_metric":     "<one sentence: how success is measured (number, deliverable, capability)>",
  "urgency":            "<none | Q-end | specific date | event-driven>",
  "alternatives_considered": "<comma-list of alternatives they mentioned: in-house, other vendors, do-nothing>",
  "tier_signal":        "<1 | 2 | 3 — best guess from scope and value language>",
  "tier_rationale":     "<one sentence explaining the tier signal>",
  "value_signal":       "<integer USD if a number is mentioned; null otherwise>",
  "deliverable_1":      "<primary deliverable if discussed>",
  "deliverable_2":      "<secondary if discussed>",
  "deliverable_3":      "<tertiary if discussed>",
  "client_team_size":   "<integer if mentioned>",
  "client_team_areas":  "<comma-list of areas: HR, IT, Engineering, etc.>",
  "access_systems":     "<comma-list of systems they have / would grant access to>",
  "scope_risks":        "<top 1-3 risks named, semicolon-separated>"
}

Omit fields you cannot fill. Return {} if the transcript has no scope-relevant content.
"""


def prefill_from_transcript(transcript_path: Path | None, deal: dict) -> int:
    """Fill deal fields from a discovery transcript via claude -p structured extraction.

    v0.2 (current): calls claude -p with SCOPE_EXTRACTION_PROMPT, parses JSON, merges.
    Falls back to heuristic regex scan if claude CLI unavailable or extraction fails.
    """
    if not transcript_path or not transcript_path.is_file():
        return 0
    text = transcript_path.read_text(errors="replace")[:80000]  # cap massive transcripts
    n = 0

    # Try Claude extraction first
    extracted = _extract_via_claude(text)
    if extracted:
        n += _merge_extraction_into_deal(extracted, deal)
        return n

    # Fallback: heuristic regex scan (the original v0.1 approach)
    problems = re.search(r"##.*Problems[:\s]*\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
    if problems and not deal.get("problem_statement"):
        first_bullet = re.search(r"^\s*[-*]\s+(.+?)$", problems.group(1), re.MULTILINE)
        if first_bullet:
            deal["problem_statement"] = first_bullet.group(1).strip()[:300]
            n += 1
    plans = re.search(r"##.*Plans[:\s]*\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
    if plans and not deal.get("target_outcome"):
        first_bullet = re.search(r"^\s*[-*]\s+(.+?)$", plans.group(1), re.MULTILINE)
        if first_bullet:
            deal["target_outcome"] = first_bullet.group(1).strip()[:300]
            n += 1
    return n


def _extract_via_claude(transcript_text: str, timeout: int = 180) -> dict | None:
    """Run claude -p with SCOPE_EXTRACTION_PROMPT; return parsed JSON object or None."""
    full_prompt = (
        f"{SCOPE_EXTRACTION_PROMPT}\n\n--- TRANSCRIPT ---\n{transcript_text}\n--- END ---\n\n"
        "Return the JSON object now."
    )
    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--settings", str(Path.home() / "Winnie" / "config" / "scheduled.settings.json"),
                "--dangerously-skip-permissions",
                full_prompt,
            ],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  ! claude CLI failed: {e}", file=sys.stderr)
        return None
    if result.returncode != 0:
        print(f"  ! claude exit {result.returncode}: {result.stderr[:200]}", file=sys.stderr)
        return None
    output = result.stdout.strip()
    output = re.sub(r"^Warning: no stdin.*?\n", "", output, count=1)
    m = re.search(r"\{[\s\S]*\}", output)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _merge_extraction_into_deal(extracted: dict, deal: dict) -> int:
    """Merge extracted fields into deal; only fill empty deal slots."""
    n = 0
    field_map = {
        "client_name":              "client_name",
        "industry":                 "industry",
        "headcount_range":          "headcount_range",
        "problem_statement":        "problem_statement",
        "target_outcome":           "target_outcome",
        "success_metric":           "success_metric",
        "urgency":                  "urgency",
        "alternatives_considered":  "alternatives_considered",
        "tier_rationale":           "tier_rationale",
        "deliverable_1":            "deliverable_1",
        "deliverable_2":            "deliverable_2",
        "deliverable_3":            "deliverable_3",
        "client_team_size":         "client_team_size",
        "client_team_areas":        "client_team_areas",
        "access_systems":           "access_systems",
        "scope_risks":              "scope_risks",
    }
    for ext_key, deal_key in field_map.items():
        v = extracted.get(ext_key)
        if v in (None, "", "null"):
            continue
        if deal.get(deal_key) in (None, ""):
            deal[deal_key] = str(v).strip()[:400]
            n += 1
    # Tier + value need special handling
    if "tier_signal" in extracted and not deal.get("tier"):
        try:
            deal["tier"] = int(extracted["tier_signal"])
            n += 1
        except (ValueError, TypeError):
            pass
    if "value_signal" in extracted and not deal.get("value"):
        try:
            deal["value"] = int(extracted["value_signal"])
            n += 1
        except (ValueError, TypeError):
            pass
    return n


def ask(label: str, default=None, required: bool = True) -> str:
    """Interactive prompt with default support. Honors stdin-not-tty by skipping."""
    if not sys.stdin.isatty():
        return str(default) if default is not None else ""
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        try:
            val = input(f"  {label}{suffix}: ").strip()
        except EOFError:
            val = ""
        if val:
            return val
        if default not in (None, ""):
            return str(default)
        if not required:
            return ""
        print("  (required)")


def walk_questionnaire(q: dict, deal: dict, ask_user: bool) -> tuple[int, int]:
    """Walk the YAML questionnaire. Returns (asked_count, prefilled_count)."""
    asked = 0
    prefilled = 0
    for section in q.get("sections", []):
        if not evaluate_when(section.get("when"), deal):
            continue
        section_questions = section.get("questions", [])
        if not section_questions:
            continue
        # Show section header only once we know we'll ask something there
        section_header_shown = False
        for question in section_questions:
            if not evaluate_when(question.get("when"), deal):
                continue
            field = question["field"]
            if not field.startswith("deal."):
                continue
            key = field.removeprefix("deal.")
            if deal.get(key) not in (None, ""):
                prefilled += 1
                continue
            if not question.get("required", False) and not ask_user:
                continue
            if ask_user and not section_header_shown:
                print(f"\n=== {section['name']} ===")
                section_header_shown = True
            if ask_user:
                val = ask(question["prompt"], required=question.get("required", False))
                if val:
                    deal[key] = val
                    asked += 1
            else:
                # Non-interactive mode: just leave unfilled
                pass
    return asked, prefilled


def write_scope_md(deal: dict, vault_path: Path, slug: str, tenant_cfg: dict) -> Path:
    out_dir = vault_path / "Solutions" / "Scopes"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}.md"

    body = ["---"]
    body.append(f"lead_slug: {slug}")
    body.append(f"created_at: {datetime.now().isoformat(timespec='seconds')}")
    body.append(f"scoper: scope-builder.py v0.1")
    if deal.get("tier"):
        body.append(f"tier: {deal['tier']}")
    if deal.get("value"):
        body.append(f"value: {deal['value']}")
    body.append("tags: [scope, alpen-platform]")
    body.append("---")
    body.append("")
    body.append(f"# Scope — {deal.get('client_name', slug)}")
    body.append("")
    if deal.get("problem_statement"):
        body.append(f"## Problem")
        body.append(deal["problem_statement"])
        body.append("")
    if deal.get("target_outcome"):
        body.append(f"## Target outcome")
        body.append(deal["target_outcome"])
        body.append("")
    if deal.get("success_metric"):
        body.append(f"## Success metric")
        body.append(deal["success_metric"])
        body.append("")
    body.append(f"## Tier")
    body.append(f"Tier {deal.get('tier', 'TBD')} — {deal.get('tier_rationale', 'rationale TBD')}")
    body.append("")
    body.append(f"## Investment")
    body.append(f"${deal.get('value', 'TBD'):,}" if isinstance(deal.get("value"), int) else f"{deal.get('value', 'TBD')}")
    body.append("")
    if deal.get("deliverable_1") or deal.get("deliverable_2") or deal.get("deliverable_3"):
        body.append("## Deliverables")
        for k in ("deliverable_1", "deliverable_2", "deliverable_3"):
            if deal.get(k):
                body.append(f"- {deal[k]}")
        body.append("")
    body.append("## Full deal context")
    body.append("```yaml")
    body.append(yaml.dump({"deal": deal}, sort_keys=False, default_flow_style=False).rstrip())
    body.append("```")
    body.append("")

    out_path.write_text("\n".join(body))
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--entity", help="Entity id; defaults to lead.entity_id or first config entity")
    parser.add_argument("--lead-slug", required=True)
    parser.add_argument("--transcript", help="Path to a discovery transcript markdown")
    parser.add_argument("--no-interactive", action="store_true",
                        help="Skip user prompts; use only auto-fills (for batch / CI)")
    parser.add_argument("--compose", action="store_true",
                        help="After scope, automatically run compose-proposal.py")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3],
                        help="Tier override (otherwise uses lead.tier or asks)")
    args = parser.parse_args()

    start = time.time()
    tenant_cfg = load_tenant_cfg(args.tenant)
    lead = load_lead(args.lead_slug)
    entity_id = args.entity or (lead.get("entity_id") if lead else None) or tenant_cfg["entities"][0]["id"]
    q = load_questionnaire(args.tenant, entity_id)

    deal: dict = {}
    n_lead = prefill_from_lead(lead, deal)
    if args.tier:
        deal["tier"] = args.tier
    transcript_path = Path(args.transcript).expanduser() if args.transcript else None
    n_trans = prefill_from_transcript(transcript_path, deal)

    print(f"=== scope-builder ===")
    print(f"tenant:     {args.tenant}")
    print(f"entity:     {entity_id}")
    print(f"lead:       {args.lead_slug}{' (not in leads.db)' if not lead else ''}")
    if transcript_path:
        print(f"transcript: {transcript_path.name}")
    print(f"prefilled:  {n_lead} from lead, {n_trans} from transcript")

    asked, total_prefilled = walk_questionnaire(q, deal, ask_user=not args.no_interactive)
    print(f"asked:      {asked}")
    print(f"resolved:   {total_prefilled + asked + n_lead + n_trans} fields total")

    vault_path = Path(os.path.expanduser(tenant_cfg["tenant"]["vault_path"]))
    out_path = write_scope_md(deal, vault_path, args.lead_slug, tenant_cfg)
    print(f"wrote scope: {out_path}")

    json_path = Path(f"/tmp/{args.lead_slug}-scope.json")
    json_path.write_text(json.dumps(deal, indent=2, default=str))
    print(f"wrote JSON:  {json_path}")

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   lead_slug=args.lead_slug, entity=entity_id,
                   tier=deal.get("tier") or 0,
                   prefilled_lead=n_lead, prefilled_transcript=n_trans,
                   asked=asked,
                   duration_seconds=round(time.time() - start, 1))

    if args.compose:
        if not deal.get("tier"):
            print("\n!! Cannot --compose without a tier. Re-run with --tier <1|2|3>.")
            return 0
        print(f"\n=== Handing off to compose-proposal --tier {deal['tier']} ===")
        py = sys.executable
        composer = PLATFORM_ROOT / "bin" / "compose-proposal.py"
        cmd = [
            py, str(composer),
            "--tenant", args.tenant, "--entity", entity_id,
            "--tier", str(deal["tier"]), "--lead-slug", args.lead_slug,
        ]
        return subprocess.call(cmd)

    return 0


if __name__ == "__main__":
    sys.exit(main())
