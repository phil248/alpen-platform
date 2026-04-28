#!/usr/bin/env python3
"""Validate Alpen Platform tenant configuration files.

Validates two file shapes:
  1. tenants/<id>/placeholders.yaml — placeholder substitution pack
  2. tenants/<id>/config.yaml       — full tenant config (when present)

Usage:
  validate-tenant-config.py --tenant phil-howard
  validate-tenant-config.py --all
  validate-tenant-config.py --tenant phil-howard --strict   (fail on any warning)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tenant_models import PlaceholderPack, TenantConfig  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
TENANTS_DIR = PLATFORM_ROOT / "tenants"


def load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def fmt_pydantic_error(e: ValidationError) -> str:
    out = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"])
        msg = err["msg"]
        out.append(f"  ✗ {loc}: {msg}")
    return "\n".join(out)


def validate_placeholders(tenant_id: str) -> tuple[bool, list[str]]:
    """Returns (ok, messages)."""
    path = TENANTS_DIR / tenant_id / "placeholders.yaml"
    msgs = []
    if not path.is_file():
        return True, [f"  - placeholders.yaml absent (optional)"]
    try:
        data = load_yaml(path)
        pack = PlaceholderPack(**data)
        msgs.append(f"  ✓ placeholders.yaml schema_version={pack.schema_version}")
        msgs.append(f"    upstream entries:         {len(pack.upstream)}")
        msgs.append(f"    alpen_extensions entries: {len(pack.alpen_extensions)}")
        # Soft warnings
        empty_upstream = sum(1 for v in pack.upstream.values() if v in (None, ""))
        msgs.append(f"    upstream entries unset:   {empty_upstream} (intentional skips)")
        return True, msgs
    except ValidationError as e:
        msgs.append(f"  ✗ placeholders.yaml FAILED:")
        msgs.append(fmt_pydantic_error(e))
        return False, msgs
    except Exception as e:
        msgs.append(f"  ✗ placeholders.yaml: {type(e).__name__}: {e}")
        return False, msgs


def validate_config(tenant_id: str) -> tuple[bool, list[str]]:
    """Returns (ok, messages)."""
    path = TENANTS_DIR / tenant_id / "config.yaml"
    msgs = []
    if not path.is_file():
        return True, [f"  - config.yaml absent (still scaffolding tenant; OK for v0.1)"]
    try:
        data = load_yaml(path)
        cfg = TenantConfig(**data)
        msgs.append(f"  ✓ config.yaml schema_version={cfg.schema_version}")
        msgs.append(f"    tenant.id:                    {cfg.tenant.id}")
        msgs.append(f"    principals:                   {len(cfg.principals)}")
        msgs.append(f"    entities:                     {len(cfg.entities)}  ({', '.join(e.id for e in cfg.entities)})")
        enabled_depts = sum(1 for d in cfg.departments.values() if d.enabled)
        msgs.append(f"    departments enabled:          {enabled_depts} of {len(cfg.departments)}")
        msgs.append(f"    rag backend:                  {cfg.data_stores.rag.backend}")
        msgs.append(f"    structured backend:           {cfg.data_stores.structured.backend}")
        msgs.append(f"    vault backend:                {cfg.data_stores.vault.backend}")
        msgs.append(f"    telemetry enabled:            {cfg.telemetry.enabled}")
        return True, msgs
    except ValidationError as e:
        msgs.append(f"  ✗ config.yaml FAILED:")
        msgs.append(fmt_pydantic_error(e))
        return False, msgs
    except Exception as e:
        msgs.append(f"  ✗ config.yaml: {type(e).__name__}: {e}")
        return False, msgs


def validate_tenant(tenant_id: str) -> bool:
    print(f"=== Validating tenant: {tenant_id} ===")
    ph_ok, ph_msgs = validate_placeholders(tenant_id)
    print("\n".join(ph_msgs))
    cfg_ok, cfg_msgs = validate_config(tenant_id)
    print("\n".join(cfg_msgs))
    return ph_ok and cfg_ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant", help="validate one tenant by id")
    group.add_argument("--all", action="store_true", help="validate every tenant in tenants/")
    parser.add_argument("--strict", action="store_true", help="reserved")
    args = parser.parse_args()

    if not TENANTS_DIR.is_dir():
        sys.exit(f"error: tenants dir not found: {TENANTS_DIR}")

    if args.all:
        tenants = sorted(p.name for p in TENANTS_DIR.iterdir() if p.is_dir())
    else:
        tenants = [args.tenant]
        if not (TENANTS_DIR / args.tenant).is_dir():
            sys.exit(f"error: no such tenant: {args.tenant}")

    all_ok = True
    for t in tenants:
        ok = validate_tenant(t)
        all_ok = all_ok and ok
        print()

    print(f"=== {'ALL TENANTS VALID' if all_ok else 'VALIDATION FAILED'} ===")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
