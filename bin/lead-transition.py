#!/usr/bin/env python3
"""Transition a lead to a terminal state (WON / LOST / DISQUALIFIED).

For WON: also create the engagement markdown file at
${VAULT}/Delivery/Engagements/<eid>.md and back-link contract_id +
engagement_id into the lead frontmatter.

Source files this script edits:
  ${VAULT}/Sales/Leads/<lead-slug>.md            (or legacy Opportunities/)
  ${VAULT}/Delivery/Engagements/<eid>.md         (created on WON)

After editing markdown, runs regenerate-leads-index.py and
regenerate-engagements-index.py so the SQLite indices stay in sync.

Usage:
  # Won — full path: lead → engagement (requires contract_id + dates)
  lead-transition.py --tenant phil-howard --lead-id calm-health \\
    --outcome won \\
    --contract-id sow-calm-health-2026q2 \\
    --kickoff-date 2026-05-15 --planned-end-date 2026-08-15 \\
    --total-value 80000 --tier 2 \\
    --close-reason "Krystal closed after Q2 board meeting"

  # Lost / disqualified — terminal but no engagement
  lead-transition.py --tenant phil-howard --lead-id calm-health \\
    --outcome lost --close-reason "Budget shifted to internal team"

  lead-transition.py --tenant phil-howard --lead-id calm-health \\
    --outcome disqualified --close-reason "Not a fit; no decision-maker access"

Won transitions REQUIRE: --contract-id, --kickoff-date, --planned-end-date.
Lost / disqualified transitions REQUIRE: --close-reason.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "lead-transition"

OUTCOME_TO_STAGE = {
    "won": "Closed - Won",
    "lost": "Closed - Lost",
    "disqualified": "Disqualified",
}


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    if not p.is_file():
        sys.exit(f"error: tenant config not found: {p}")
    with p.open() as f:
        return yaml.safe_load(f) or {}


def vault_path(tenant_cfg: dict) -> Path:
    raw = tenant_cfg.get("tenant", {}).get("vault_path") or os.environ.get("VAULT_PATH")
    if not raw:
        sys.exit("error: tenant.vault_path not set and VAULT_PATH not in env")
    return Path(os.path.expanduser(raw))


def find_lead_file(vault: Path, lead_id: str) -> Path:
    candidates = [
        vault / "Sales" / "Leads" / f"{lead_id}.md",
        vault / "Cognitive-Capital-Group" / "Opportunities" / f"{lead_id}.md",
    ]
    for c in candidates:
        if c.is_file():
            return c
    sys.exit(f"error: lead file for {lead_id!r} not found in any of: {[str(c) for c in candidates]}")


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        sys.exit("error: lead file missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        sys.exit("error: malformed YAML frontmatter")
    fm = yaml.safe_load(text[4:end]) or {}
    body = text[end + 5:]
    return fm, body


def render_frontmatter(fm: dict) -> str:
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, default_flow_style=False, allow_unicode=True) + "---\n"


def update_lead_file(lead_path: Path, outcome: str, close_reason: str,
                     contract_id: str | None, engagement_id: str | None,
                     today_iso: str) -> dict:
    """Update lead markdown: frontmatter + append history entry. Returns the updated frontmatter."""
    text = lead_path.read_text()
    fm, body = split_frontmatter(text)

    new_stage = OUTCOME_TO_STAGE[outcome]
    fm["stage"] = new_stage
    fm["stage_entered_date"] = today_iso
    fm["closed_at"] = today_iso
    fm["close_reason"] = close_reason
    if contract_id:
        fm["contract_id"] = contract_id
    if engagement_id:
        fm["engagement_id"] = engagement_id

    # Append history entry. Most recent on top per existing convention.
    history_marker = "## History"
    history_block = (
        f"### {today_iso} - Lead transitioned to {new_stage}\n"
        f"- Outcome: {outcome.upper()}\n"
        f"- Reason: {close_reason}\n"
    )
    if contract_id:
        history_block += f"- Contract: {contract_id}\n"
    if engagement_id:
        history_block += f"- Engagement: {engagement_id}\n"
    history_block += "\n"

    if history_marker in body:
        # Insert new entry directly under the History heading + comment line
        idx = body.find(history_marker)
        # Skip the heading line + any "<!-- ... -->" comment line
        line_end = body.find("\n", idx) + 1
        # If the next non-empty line is a comment, skip past it too
        rest = body[line_end:]
        if rest.lstrip().startswith("<!--"):
            comment_end = rest.find("-->")
            if comment_end >= 0:
                line_end += comment_end + len("-->\n")
                if body[line_end:line_end+1] == "\n":
                    line_end += 1
        body = body[:line_end] + "\n" + history_block + body[line_end:]
    else:
        body = body.rstrip() + "\n\n## History\n\n" + history_block

    lead_path.write_text(render_frontmatter(fm) + body)
    return fm


def create_engagement_file(vault: Path, eid: str, lead_fm: dict, args) -> Path:
    """Create the engagement markdown file. Returns the path written."""
    out_dir = vault / "Delivery" / "Engagements"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{eid}.md"
    if out_path.exists():
        sys.exit(f"error: engagement file already exists at {out_path}; use --engagement-id to choose a different slug")

    today_iso = datetime.now().strftime("%Y-%m-%d")
    fm = {
        "id": eid,
        "name": args.engagement_name or lead_fm.get("name") or eid,
        "entity_id": lead_fm.get("entity_id") or args.entity or "ccg",
        "client_name": args.client_name or lead_fm.get("company") or lead_fm.get("name") or "TBD",
        "tier": args.tier or lead_fm.get("tier") or 2,
        "status": "NEW",
        "kickoff_date": args.kickoff_date,
        "planned_end_date": args.planned_end_date,
        "principal_owner": args.principal_owner or lead_fm.get("owner") or "phil",
        "contract_id": args.contract_id,
        "msa_contract_id": args.msa_contract_id,
        "total_value": args.total_value,
        "client_poc_name": args.client_poc_name or lead_fm.get("primary_contact"),
        "client_poc_email": args.client_poc_email or lead_fm.get("contact_email"),
        "client_sponsor_name": args.client_sponsor_name,
        "lead_id": lead_fm.get("id") or args.lead_id,
        "created_from": f"lead-transition.py on {today_iso}",
        "tags": ["engagement", lead_fm.get("entity_id") or "ccg"],
    }
    # Drop None values (sqlite-empty fields are fine but the markdown shouldn't show "key: null")
    fm = {k: v for k, v in fm.items() if v is not None}

    body = f"""# {fm['name']}

## Engagement summary

Tier {fm['tier']} engagement with {fm['client_name']}, kicked off via the standard
delivery flow. Source lead: `{fm['lead_id']}` (transitioned {today_iso}).

## Goals

- TBD - fill from accepted proposal / SOW
- TBD
- TBD

## Deliverables

(populate from SOW; the engagements regenerator parses a `deliverables:` list
in this frontmatter as well — add inline once the SOW is signed)

## Schedule

| Milestone | Target |
|---|---|
| Kickoff | {fm.get('kickoff_date', 'TBD')} |
| Mid-sprint demo | TBD |
| Final delivery | TBD |
| Acceptance | TBD |

## Team

- Principal owner: {fm['principal_owner']}
- Client POC: {fm.get('client_poc_name', 'TBD')}
- Client sponsor: {fm.get('client_sponsor_name', 'TBD')}

## Risks

- TBD - identify at kickoff

## History

<!-- Append-only. Most recent entries on top. -->

### {today_iso} - Engagement created from lead transition
- Source lead: `{fm['lead_id']}`
- Contract: {fm['contract_id']}
- Status at creation: NEW
- Next: schedule kickoff and run compose-kickoff.py
"""
    out_path.write_text(render_frontmatter(fm) + body)
    return out_path


def run_regenerator(script_name: str, tenant: str) -> bool:
    """Invoke a regenerator and surface non-zero exit; return True on success."""
    cmd = [sys.executable, str(PLATFORM_ROOT / "bin" / script_name), "--tenant", tenant]
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"  ! {script_name} failed (exit {result.returncode}):", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--lead-id", required=True, help="lead slug (matches markdown filename without .md)")
    parser.add_argument("--outcome", required=True, choices=["won", "lost", "disqualified"])
    parser.add_argument("--close-reason", required=True, help="why won / why lost / why disqualified")
    # WON-only fields
    parser.add_argument("--engagement-id", help="engagement slug (default: lead-id)")
    parser.add_argument("--engagement-name", help="display name (default: lead.name)")
    parser.add_argument("--contract-id", help="REQUIRED for won: contracts.db SOW id")
    parser.add_argument("--msa-contract-id", help="parent MSA id")
    parser.add_argument("--kickoff-date", help="REQUIRED for won: ISO YYYY-MM-DD")
    parser.add_argument("--planned-end-date", help="REQUIRED for won: ISO YYYY-MM-DD")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3])
    parser.add_argument("--total-value", type=int, help="USD")
    parser.add_argument("--principal-owner", help="phil | krystal")
    parser.add_argument("--client-name")
    parser.add_argument("--client-poc-name")
    parser.add_argument("--client-poc-email")
    parser.add_argument("--client-sponsor-name")
    parser.add_argument("--entity", help="ccg | alpen-tech (overrides lead.entity_id)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-regenerate", action="store_true",
                        help="don't run regenerate-{leads,engagements}-index after editing")
    args = parser.parse_args()

    if args.outcome == "won":
        missing = [f for f, v in {
            "--contract-id": args.contract_id,
            "--kickoff-date": args.kickoff_date,
            "--planned-end-date": args.planned_end_date,
        }.items() if not v]
        if missing:
            sys.exit(f"error: --outcome won requires: {', '.join(missing)}")

    start = time.time()
    today_iso = datetime.now().strftime("%Y-%m-%d")
    tenant_cfg = load_tenant_cfg(args.tenant)
    vault = vault_path(tenant_cfg)
    lead_path = find_lead_file(vault, args.lead_id)

    print(f"=== lead-transition ({args.outcome}) ===")
    print(f"lead:     {args.lead_id}  ({lead_path})")
    print(f"outcome:  {args.outcome.upper()}")
    print(f"reason:   {args.close_reason}")

    eid = None
    eng_path = None
    if args.outcome == "won":
        eid = args.engagement_id or args.lead_id
        print(f"engagement: {eid}")
        print(f"contract:   {args.contract_id}")
        print(f"window:     {args.kickoff_date} → {args.planned_end_date}")
        print(f"value:      ${args.total_value:,}" if args.total_value else "value:      TBD")

    if args.dry_run:
        print("\n--- dry-run; no files modified ---")
        emit_telemetry(SCRIPT_NAME, outcome="success", dry_run=True,
                       lead_outcome=args.outcome, lead_id=args.lead_id)
        return 0

    # 1. Read current lead frontmatter to seed engagement file (if won)
    text = lead_path.read_text()
    lead_fm_pre, _ = split_frontmatter(text)

    # 2. Create engagement file (WON only) — fail-fast before touching the lead
    if args.outcome == "won":
        eng_path = create_engagement_file(vault, eid, lead_fm_pre, args)
        print(f"wrote engagement: {eng_path}")

    # 3. Update lead markdown (frontmatter + history)
    updated_fm = update_lead_file(
        lead_path, args.outcome, args.close_reason,
        contract_id=args.contract_id if args.outcome == "won" else None,
        engagement_id=eid,
        today_iso=today_iso,
    )
    print(f"updated lead:     {lead_path}")
    print(f"  stage:          {lead_fm_pre.get('stage')!r} -> {updated_fm['stage']!r}")

    # 4. Re-run regenerators so SQLite catches up with markdown
    leads_ok = engagements_ok = True
    if not args.skip_regenerate:
        print("\nregenerating indices:")
        leads_ok = run_regenerator("regenerate-leads-index.py", args.tenant)
        if args.outcome == "won":
            engagements_ok = run_regenerator("regenerate-engagements-index.py", args.tenant)

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   lead_id=args.lead_id, lead_outcome=args.outcome,
                   engagement_created=int(args.outcome == "won"),
                   leads_index_ok=int(leads_ok),
                   engagements_index_ok=int(engagements_ok),
                   duration_seconds=round(time.time() - start, 2))
    return 0 if (leads_ok and engagements_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
