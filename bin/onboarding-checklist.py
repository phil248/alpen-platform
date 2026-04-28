#!/usr/bin/env python3
"""Per-engagement onboarding state probe.

Given an engagement id, reports the state of every step in the standard
customer onboarding flow:

  1. Engagement charter created      ($VAULT/Delivery/Engagements/<id>.md)
  2. MSA drafted                     (contracts.db: type=MSA, status=DRAFT+)
  3. MSA sent for signature          (contracts.db: status >= SENT_FOR_SIGNATURE)
  4. MSA fully executed              (contracts.db: status=EXECUTED)
  5. SOW drafted                     (contracts.db: type=SOW + parent=MSA)
  6. SOW sent for signature
  7. SOW fully executed
  8. Kickoff deck composed           (filesystem: Engagements/<id>/kickoff.md)
  9. Kickoff meeting scheduled       (skipped — read calendar = manual today)
 10. Engagement status = ACTIVE      (engagements.db: status='ACTIVE')
 11. First status report sent        (engagements.db: engagement_status_report row)

For each item: ✓ done / ⏳ in progress / ◯ not started / — N/A.

Pure read; no state mutation. Phil runs this at any point during onboarding
to see "what's next."

Usage:
  onboarding-checklist.py --tenant phil-howard --engagement-id <id>
  onboarding-checklist.py --tenant phil-howard --engagement-id <id> --write   # save to vault
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "onboarding-checklist"
ENGAGEMENTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/engagements.db"))
CONTRACTS_DB = Path(os.path.expanduser("~/.local/state/alpen/sqlite/contracts.db"))


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def vault_path(tenant_cfg: dict) -> Path:
    raw = tenant_cfg.get("tenant", {}).get("vault_path") or os.environ.get("VAULT_PATH")
    if not raw:
        sys.exit("error: tenant.vault_path not set and VAULT_PATH not in env")
    return Path(os.path.expanduser(raw))


def load_engagement(eid: str) -> dict | None:
    if not ENGAGEMENTS_DB.is_file():
        return None
    conn = sqlite3.connect(ENGAGEMENTS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM engagement WHERE id = ?", (eid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def load_contracts(eid: str, msa_id: str | None) -> tuple[dict | None, dict | None]:
    """Return (msa_row, sow_row). msa_row may also come from msa_contract_id reference."""
    if not CONTRACTS_DB.is_file():
        return None, None
    conn = sqlite3.connect(CONTRACTS_DB)
    conn.row_factory = sqlite3.Row
    sow = conn.execute(
        "SELECT * FROM contract WHERE engagement_id = ? AND contract_type = 'SOW' "
        "ORDER BY created_at DESC LIMIT 1", (eid,),
    ).fetchone()
    msa = None
    if msa_id:
        msa = conn.execute("SELECT * FROM contract WHERE id = ?", (msa_id,)).fetchone()
    if not msa and sow and sow["parent_contract_id"]:
        msa = conn.execute(
            "SELECT * FROM contract WHERE id = ?", (sow["parent_contract_id"],)
        ).fetchone()
    conn.close()
    return (dict(msa) if msa else None), (dict(sow) if sow else None)


def load_first_status_report(eid: str) -> dict | None:
    if not ENGAGEMENTS_DB.is_file():
        return None
    conn = sqlite3.connect(ENGAGEMENTS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM engagement_status_report WHERE engagement_id = ? "
        "ORDER BY week_start_date ASC LIMIT 1", (eid,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# Map contract.status to a workflow phase: drafted → sent → executed
DRAFTED_STATUSES = {"DRAFT", "IN_REVIEW", "NEGOTIATING"}
SENT_STATUSES = {"SENT_FOR_SIGNATURE", "SIGNED_PARTIAL"}
EXECUTED_STATUSES = {"EXECUTED", "AMENDED"}


def contract_phase(c: dict | None) -> tuple[str, str, str]:
    """Return (drafted_mark, sent_mark, executed_mark) where each is one of:
       ✓ done / ⏳ in progress / ◯ not started / — N/A."""
    if not c:
        return "◯", "◯", "◯"
    status = c["status"]
    if status in DRAFTED_STATUSES:
        return "✓", "⏳", "◯"
    if status in SENT_STATUSES:
        return "✓", "✓", "⏳" if status == "SIGNED_PARTIAL" else "◯"
    if status in EXECUTED_STATUSES:
        return "✓", "✓", "✓"
    if status in {"EXPIRED", "TERMINATED", "VOIDED"}:
        return "—", "—", "—"
    return "◯", "◯", "◯"


def render_checklist(eid: str, eng: dict | None, msa: dict | None, sow: dict | None,
                     vault: Path, first_status: dict | None) -> list[str]:
    today = datetime.now().strftime("%Y-%m-%d")
    out = [f"# Onboarding checklist — {eid}", "",
           f"_Probed {today}. Source: engagements.db, contracts.db, filesystem._",
           ""]

    # 1. Charter
    charter_path = vault / "Delivery" / "Engagements" / f"{eid}.md"
    charter_done = "✓" if charter_path.is_file() else "◯"
    out.append(f"- {charter_done} **Engagement charter**: `{charter_path.relative_to(vault)}`")
    if not charter_done == "✓":
        out.append("    - Run `lead-transition.py --outcome won` to create from a lead, "
                    "or write directly.")

    # 2-4. MSA
    msa_d, msa_s, msa_e = contract_phase(msa)
    if msa:
        out.append(f"- {msa_d} **MSA drafted**: `{msa['id']}` ({msa['display_name']})")
        out.append(f"- {msa_s} **MSA sent for signature**")
        out.append(f"- {msa_e} **MSA fully executed**")
        if msa["executed_at"]:
            out.append(f"    - Executed: {msa['executed_at']}")
    else:
        out.append("- ◯ **MSA drafted**: not found")
        out.append("    - Run `compose-msa.py --tenant <id> --entity <eid> "
                    "--client-name '...' --client-legal-name '...' ...`")
        out.append("- ◯ **MSA sent for signature**")
        out.append("- ◯ **MSA fully executed**")

    # 5-7. SOW
    sow_d, sow_s, sow_e = contract_phase(sow)
    if sow:
        out.append(f"- {sow_d} **SOW drafted**: `{sow['id']}` ({sow['display_name']})")
        out.append(f"- {sow_s} **SOW sent for signature**")
        out.append(f"- {sow_e} **SOW fully executed**")
    else:
        out.append("- ◯ **SOW drafted**: not found")
        out.append("    - Run `compose-sow.py --tenant <id> --engagement-id "
                    f"{eid} --msa-contract-id <msa> ...`")
        out.append("- ◯ **SOW sent for signature**")
        out.append("- ◯ **SOW fully executed**")

    # 8. Kickoff deck
    kickoff_path = vault / "Delivery" / "Engagements" / eid / "kickoff.md"
    kickoff_done = "✓" if kickoff_path.is_file() else "◯"
    out.append(f"- {kickoff_done} **Kickoff deck composed**: `{kickoff_path.relative_to(vault)}`")
    if kickoff_done != "✓":
        out.append(f"    - Run `compose-kickoff.py --tenant <id> --engagement-id {eid}`")

    # 9. Kickoff meeting scheduled — manual / calendar
    out.append("- ◯ **Kickoff meeting scheduled** _(manual: schedule via Google Calendar)_")

    # 10. Status = ACTIVE
    if eng:
        active_done = "✓" if eng["status"] == "ACTIVE" else (
            "⏳" if eng["status"] == "KICKOFF" else "◯"
        )
        out.append(f"- {active_done} **Engagement status = ACTIVE** "
                    f"(currently `{eng['status']}`)")
        if active_done != "✓":
            out.append("    - Update `status:` in the engagement charter frontmatter, "
                       "then run `regenerate-engagements-index.py`")
    else:
        out.append("- ◯ **Engagement status = ACTIVE** (engagement row not found)")

    # 11. First status report
    if first_status:
        out.append(f"- ✓ **First status report sent**: week of "
                    f"{first_status['week_start_date']}")
    else:
        out.append("- ◯ **First status report sent**: not yet")
        out.append("    - Auto-fires Friday 07:25 once status=ACTIVE; "
                    f"or run manually: `compose-status-report.py --tenant <id> --engagement-id {eid}`")

    out.append("")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--engagement-id", required=True)
    parser.add_argument("--write", action="store_true",
                        help="Save to $VAULT/Delivery/Engagements/<eid>/onboarding.md")
    args = parser.parse_args()

    start = time.time()
    tenant_cfg = load_tenant_cfg(args.tenant)
    vault = vault_path(tenant_cfg)

    eng = load_engagement(args.engagement_id)
    if not eng:
        print(f"warning: engagement {args.engagement_id!r} not in engagements.db; "
              f"checking filesystem only")
    msa, sow = load_contracts(args.engagement_id,
                                 eng.get("msa_contract_id") if eng else None)
    first_status = load_first_status_report(args.engagement_id)

    lines = render_checklist(args.engagement_id, eng, msa, sow, vault, first_status)
    text = "\n".join(lines)

    if args.write:
        out_dir = vault / "Delivery" / "Engagements" / args.engagement_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "onboarding.md"
        out_path.write_text(text + "\n")
        print(f"wrote: {out_path}\n")

    print(text)

    # Count completed steps for telemetry
    done_count = sum(1 for ln in lines if ln.startswith("- ✓"))
    in_progress_count = sum(1 for ln in lines if ln.startswith("- ⏳"))
    not_started_count = sum(1 for ln in lines if ln.startswith("- ◯"))

    emit_telemetry(SCRIPT_NAME, outcome="success",
                   engagement_id=args.engagement_id,
                   steps_done=done_count,
                   steps_in_progress=in_progress_count,
                   steps_not_started=not_started_count,
                   has_engagement_row=int(eng is not None),
                   has_msa=int(msa is not None),
                   has_sow=int(sow is not None),
                   duration_seconds=round(time.time() - start, 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
