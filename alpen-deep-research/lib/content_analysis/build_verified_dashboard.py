#!/usr/bin/env python3
"""Build the inventory verified-dashboard from disk + SQLite (no LLM).

Single callable entry point: ``build_dashboard(inventory_root, rag_db_path,
output_md_path)``. Replaces the prose ``op=build_verified_dashboard`` in
``alpen-deep-research/skills/content-analysis/SKILL.md``.

Idempotent: re-running against the same inputs produces identical markdown
output (records sorted; counts are deterministic).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Entity-kind directories enumerated in the SKILL.md.
ENTITY_KINDS: tuple[str, ...] = (
    "publications",
    "media-mentions",
    "amplifications",
    "speaking-engagements",
    "awards-received",
    "awards-given",
    "patents",
    "projects",
    "events",
    "public-presence",
    "people",
    "books",
    "owned-content",
    "citations",
)

ASSET_PATH_FIELDS: tuple[str, ...] = (
    "transcript_local_path",
    "pdf_local_path",
    "html_local_path",
)

ORCID_TIMEOUT_S: float = 15.0


def _count_jsons(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for _ in directory.glob("*.json"))


def _asset_coverage_for_kind(directory: Path) -> dict[str, int]:
    """Count records that populate each asset path field."""
    coverage = {field: 0 for field in ASSET_PATH_FIELDS}
    if not directory.is_dir():
        return coverage
    for jf in sorted(directory.glob("*.json")):
        try:
            with jf.open("r", encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        # The fields can live at the top level or under raw_json (older shape).
        merged: dict[str, Any] = {}
        if isinstance(rec, dict):
            merged.update(rec)
            raw = rec.get("raw_json")
            if isinstance(raw, dict):
                for k, v in raw.items():
                    merged.setdefault(k, v)
        for field in ASSET_PATH_FIELDS:
            val = merged.get(field)
            if isinstance(val, str) and val.strip():
                coverage[field] += 1
    return coverage


def _rag_state(rag_db_path: Path) -> dict[str, dict[str, int]]:
    """Per source_kind: chunk count + distinct source_path count."""
    out: dict[str, dict[str, int]] = {}
    if not rag_db_path.exists():
        return out
    try:
        conn = sqlite3.connect(f"file:{rag_db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    try:
        cur = conn.execute(
            "SELECT source_kind, COUNT(*) AS chunks, "
            "COUNT(DISTINCT source_path) AS paths "
            "FROM chunks GROUP BY source_kind ORDER BY source_kind"
        )
        for source_kind, chunks, paths in cur.fetchall():
            out[source_kind or "(unknown)"] = {
                "chunks": int(chunks),
                "distinct_paths": int(paths),
            }
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return out


def _orcid_works_count(orcid: str) -> int | None:
    """Query pub.orcid.org for ground-truth works count. Returns None on error."""
    orcid = orcid.strip()
    if not orcid:
        return None
    url = f"https://pub.orcid.org/v3.0/{orcid}/works"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=ORCID_TIMEOUT_S) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    groups = payload.get("group") or []
    return len(groups) if isinstance(groups, list) else None


def _people_with_orcid(people_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not people_dir.is_dir():
        return out
    for jf in sorted(people_dir.glob("*.json")):
        try:
            with jf.open("r", encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rec, dict):
            continue
        merged: dict[str, Any] = dict(rec)
        raw = rec.get("raw_json")
        if isinstance(raw, dict):
            for k, v in raw.items():
                merged.setdefault(k, v)
        orcid = merged.get("orcid") or merged.get("ORCID")
        if not isinstance(orcid, str) or not orcid.strip():
            continue
        canonical = (
            merged.get("canonical_name")
            or merged.get("title")
            or jf.stem
        )
        out.append({"slug": jf.stem, "canonical_name": canonical, "orcid": orcid.strip()})
    return out


def _inventory_pubs_for_person(
    publications_dir: Path, person_canonical: str
) -> int:
    """Count publications whose authors include the given canonical name.

    Naive substring match (case-insensitive on last token); good enough for
    delta_pct headline.
    """
    if not publications_dir.is_dir():
        return 0
    needle = person_canonical.strip().lower()
    if not needle:
        return 0
    last_token = needle.split()[-1] if needle else ""
    count = 0
    for jf in publications_dir.glob("*.json"):
        try:
            with jf.open("r", encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rec, dict):
            continue
        authors = rec.get("authors")
        if isinstance(authors, list):
            for a in authors:
                name = a.get("name") if isinstance(a, dict) else (a if isinstance(a, str) else "")
                name_l = (name or "").lower()
                if needle in name_l or (last_token and last_token in name_l):
                    count += 1
                    break
        elif isinstance(authors, str) and last_token and last_token in authors.lower():
            count += 1
    return count


def _orcid_truth_check(
    inventory_root: Path, skip_orcid: bool = False
) -> list[dict[str, Any]]:
    people_dir = inventory_root / "people"
    publications_dir = inventory_root / "publications"
    rows: list[dict[str, Any]] = []
    for person in _people_with_orcid(people_dir):
        inv_count = _inventory_pubs_for_person(publications_dir, person["canonical_name"])
        orcid_count = None if skip_orcid else _orcid_works_count(person["orcid"])
        delta_pct: float | None
        if orcid_count is None or orcid_count == 0:
            delta_pct = None
        else:
            delta_pct = round((inv_count - orcid_count) / orcid_count * 100.0, 1)
        rows.append(
            {
                "slug": person["slug"],
                "canonical_name": person["canonical_name"],
                "orcid": person["orcid"],
                "orcid_count": orcid_count,
                "inventory_count": inv_count,
                "delta_pct": delta_pct,
            }
        )
    rows.sort(key=lambda r: r["canonical_name"].lower())
    return rows


def _render_markdown(
    inventory_root: Path,
    counts_by_kind: dict[str, int],
    asset_coverage: dict[str, dict[str, int]],
    rag_state: dict[str, dict[str, int]],
    orcid_rows: list[dict[str, Any]],
    timestamp: str,
) -> str:
    lines: list[str] = []
    lines.append("# Verified Inventory Dashboard")
    lines.append("")
    lines.append(f"- Inventory root: `{inventory_root}`")
    lines.append(f"- Generated (UTC): {timestamp}")
    lines.append(
        "- Source: deterministic Python "
        "(`lib/content_analysis/build_verified_dashboard.py`)"
    )
    lines.append("")
    lines.append("## Entity counts by kind")
    lines.append("")
    lines.append("| Kind | On-disk JSON | RAG chunks | RAG distinct paths |")
    lines.append("|---|---:|---:|---:|")
    for kind in ENTITY_KINDS:
        rag = rag_state.get(kind, {"chunks": 0, "distinct_paths": 0})
        lines.append(
            f"| {kind} | {counts_by_kind.get(kind, 0)} | "
            f"{rag['chunks']} | {rag['distinct_paths']} |"
        )
    # Surface any RAG source_kinds that are not in our enumeration.
    extra = [k for k in rag_state if k not in ENTITY_KINDS]
    for kind in sorted(extra):
        rag = rag_state[kind]
        lines.append(
            f"| {kind} (rag-only) | 0 | {rag['chunks']} | {rag['distinct_paths']} |"
        )
    lines.append("")
    lines.append("## Asset coverage")
    lines.append("")
    lines.append("| Kind | transcript_local_path | pdf_local_path | html_local_path |")
    lines.append("|---|---:|---:|---:|")
    for kind in ENTITY_KINDS:
        cov = asset_coverage.get(kind, {f: 0 for f in ASSET_PATH_FIELDS})
        lines.append(
            f"| {kind} | {cov['transcript_local_path']} | "
            f"{cov['pdf_local_path']} | {cov['html_local_path']} |"
        )
    lines.append("")
    lines.append("## ORCID truth-check (Stage 3.5)")
    lines.append("")
    if not orcid_rows:
        lines.append("_No people records with `orcid` populated._")
    else:
        lines.append(
            "| Canonical name | ORCID | ORCID works | Inventory pubs | Δ % |"
        )
        lines.append("|---|---|---:|---:|---:|")
        for row in orcid_rows:
            orcid_count = "?" if row["orcid_count"] is None else row["orcid_count"]
            delta = "" if row["delta_pct"] is None else f"{row['delta_pct']:+.1f}"
            lines.append(
                f"| {row['canonical_name']} | {row['orcid']} | "
                f"{orcid_count} | {row['inventory_count']} | {delta} |"
            )
    lines.append("")
    return "\n".join(lines)


def build_dashboard(
    inventory_root: str,
    rag_db_path: str,
    output_md_path: str,
    skip_orcid: bool = False,
) -> dict[str, Any]:
    """Compute inventory health dashboard from disk + SQLite (no LLM synthesis).

    Args:
        inventory_root: Absolute path to the per-client inventory root
            (e.g., ``.../Client-Inventories/CBH``).
        rag_db_path: Absolute path to the per-client RAG SQLite store
            (e.g., ``~/Winnie/data/client-inventories/cbh/rag.db``).
        output_md_path: Absolute path for the rendered dashboard markdown.
        skip_orcid: When True, skip live ORCID lookups (useful for offline
            smoke tests). Default False.

    Returns:
        Dict with keys ``counts_by_kind``, ``asset_coverage``, ``rag_state``,
        ``orcid_truth_check``, ``output_md_path``.
    """
    root = Path(inventory_root)
    rag_path = Path(rag_db_path)
    out_path = Path(output_md_path)

    counts_by_kind = {kind: _count_jsons(root / kind) for kind in ENTITY_KINDS}
    asset_coverage = {
        kind: _asset_coverage_for_kind(root / kind) for kind in ENTITY_KINDS
    }
    rag_state = _rag_state(rag_path)
    orcid_rows = _orcid_truth_check(root, skip_orcid=skip_orcid)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    md = _render_markdown(
        root, counts_by_kind, asset_coverage, rag_state, orcid_rows, timestamp
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(md, encoding="utf-8")
    tmp.replace(out_path)

    # Provenance sidecar.
    prov = out_path.with_suffix(out_path.suffix + ".provenance.json")
    prov_payload = {
        "inventory_root": str(root),
        "rag_db_path": str(rag_path),
        "generated_at_utc": timestamp,
        "counts_by_kind": counts_by_kind,
        "asset_coverage": asset_coverage,
        "rag_state": rag_state,
        "orcid_truth_check_skipped": skip_orcid,
        "orcid_rows": orcid_rows,
    }
    prov_tmp = prov.with_suffix(prov.suffix + ".tmp")
    prov_tmp.write_text(json.dumps(prov_payload, indent=2, sort_keys=True), encoding="utf-8")
    prov_tmp.replace(prov)

    return {
        "counts_by_kind": counts_by_kind,
        "asset_coverage": asset_coverage,
        "rag_state": rag_state,
        "orcid_truth_check": orcid_rows,
        "output_md_path": str(out_path),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the verified inventory dashboard."
    )
    parser.add_argument(
        "--inventory-root",
        required=True,
        help="Absolute path to per-client inventory root",
    )
    parser.add_argument(
        "--rag-db",
        required=True,
        help="Absolute path to per-client RAG SQLite DB",
    )
    parser.add_argument(
        "--output", required=True, help="Absolute path for dashboard markdown"
    )
    parser.add_argument(
        "--skip-orcid",
        action="store_true",
        help="Skip live ORCID lookups (offline mode)",
    )
    args = parser.parse_args()

    result = build_dashboard(
        args.inventory_root, args.rag_db, args.output, skip_orcid=args.skip_orcid
    )
    summary = {
        "output_md_path": result["output_md_path"],
        "counts_by_kind": result["counts_by_kind"],
        "rag_kinds": sorted(result["rag_state"].keys()),
        "orcid_rows": len(result["orcid_truth_check"]),
    }
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
