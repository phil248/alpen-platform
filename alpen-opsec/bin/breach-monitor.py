#!/usr/bin/env python3
"""Check Have I Been Pwned for any breach against the principal's known emails.

Reads tenant.principals[].accounts[].address (kind=gmail) as the input list.
Calls HIBP /api/v3/breachedaccount/{email} for each, with rate limiting.

If the env var HIBP_API_KEY is not set, the script exits 0 with a one-line
"skipped" message — the framework is in place but disabled. Set the key
to activate. (HIBP free tier requires a $3.95/mo subscription for the
breachedaccount endpoint; the k-anonymized password endpoint is free but
requires plaintext passwords, which this script does NOT handle.)

Output (only when HIBP_API_KEY is set and breaches are found):
  $VAULT/HFO/OPSEC/Breach-Log/YYYY-MM-DD-breaches.md

State file (so daily reports surface NEW breaches, not the full history):
  ~/.local/state/alpen/opsec/breach-state.json
  Per-email map: { "<email>": ["<breach-name>", ...] }

Usage:
  HIBP_API_KEY=xxx breach-monitor.py --tenant phil-howard
  HIBP_API_KEY=xxx breach-monitor.py --tenant phil-howard --dry-run
  breach-monitor.py --tenant phil-howard       # exits 0 with "skipped"

Privacy:
  - Emails are sent to HIBP over HTTPS. HIBP itself does not log breached
    account queries (per their privacy policy). For maximum paranoia,
    use the k-anonymous password lookup instead — but that's password
    hashes, not emails.
  - State file is local; never committed to git (lives outside vault).
  - Telemetry emits counts only, never email addresses or breach names.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "bin"))
from _regenerator_lib import emit_telemetry  # noqa: E402

PLATFORM_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_NAME = "breach-monitor"

HIBP_BASE = "https://haveibeenpwned.com/api/v3"
HIBP_USER_AGENT = "alpen-opsec/breach-monitor (https://github.com/phil248/alpen-platform)"
HIBP_MIN_INTERVAL_SECONDS = 1.6  # HIBP rate limit: ~1 req/sec on lowest tier; +safety

STATE_DIR = Path(os.path.expanduser("~/.local/state/alpen/opsec"))
STATE_FILE = STATE_DIR / "breach-state.json"


def load_tenant_cfg(tenant_id: str) -> dict:
    p = PLATFORM_ROOT / "tenants" / tenant_id / "config.yaml"
    with p.open() as f:
        return yaml.safe_load(f) or {}


def vault_path(tenant_cfg: dict) -> Path:
    raw = tenant_cfg.get("tenant", {}).get("vault_path") or os.environ.get("VAULT_PATH")
    if not raw:
        sys.exit("error: tenant.vault_path not set and VAULT_PATH not in env")
    return Path(os.path.expanduser(raw))


def collect_emails(tenant_cfg: dict) -> list[tuple[str, str]]:
    """Return list of (email, principal_name)."""
    out: list[tuple[str, str]] = []
    for p in tenant_cfg.get("principals") or []:
        name = p.get("name") or p.get("id") or "unknown"
        for acct in p.get("accounts") or []:
            if acct.get("kind") != "gmail":
                continue
            addr = acct.get("address")
            if addr:
                out.append((addr, name))
    return out


def hibp_check_email(email: str, api_key: str) -> tuple[list[dict], int]:
    """Call HIBP /breachedaccount/{email}. Return (breaches, status_code).

    Status 404 = no breaches (empty list). 200 = list of breaches.
    Anything else logged but not raised — script continues with other emails.
    """
    enc = urllib.parse.quote(email)
    url = f"{HIBP_BASE}/breachedaccount/{enc}?truncateResponse=false"
    req = urllib.request.Request(url, headers={
        "hibp-api-key": api_key,
        "user-agent": HIBP_USER_AGENT,
        "accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8")) or [], resp.status
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return [], 404
        return [], e.code
    except Exception:
        return [], 0


def load_state() -> dict:
    if not STATE_FILE.is_file():
        return {}
    try:
        with STATE_FILE.open() as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def render_report(new_breaches_by_email: dict[str, list[dict]],
                   all_breaches_by_email: dict[str, list[dict]],
                   email_to_principal: dict[str, str]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    out = [
        f"# Breach monitor — {today}",
        "",
        "_Source: Have I Been Pwned `/api/v3/breachedaccount`._",
        "",
    ]
    new_count = sum(len(v) for v in new_breaches_by_email.values())
    if new_count == 0:
        out += [
            "## Status: clean",
            "",
            f"No new breaches across {len(all_breaches_by_email)} monitored email(s).",
            "",
            "Historical breaches are tracked in the local state file but suppressed",
            "from this report; only NEW breaches detected since the previous run",
            "are surfaced here.",
            "",
        ]
    else:
        out += [
            f"## NEW BREACHES DETECTED — {new_count} across {sum(1 for v in new_breaches_by_email.values() if v)} email(s)",
            "",
            "| Email | Principal | Breach | Date | Pwn count | Data classes |",
            "|---|---|---|---|---|---|",
        ]
        for email, breaches in new_breaches_by_email.items():
            if not breaches:
                continue
            for b in breaches:
                name = b.get("Name", "?")
                date = b.get("BreachDate", "?")
                pwn = f"{b.get('PwnCount', 0):,}"
                data = ", ".join(b.get("DataClasses", [])[:5])
                if len(b.get("DataClasses", [])) > 5:
                    data += f", +{len(b['DataClasses']) - 5} more"
                out.append(f"| {email} | {email_to_principal.get(email, '?')} | "
                            f"{name} | {date} | {pwn} | {data} |")
        out.append("")
        out += [
            "## Recommended actions",
            "",
            "1. Rotate the password used at the breached service (and any reuses).",
            "2. Force sign-out of all sessions and re-authenticate.",
            "3. Enable MFA on the affected account if not already.",
            "4. Review recent activity / login history for the affected account.",
            "5. If the breach exposed PII beyond credentials, evaluate credit-freeze.",
            "",
        ]
    out += [
        "## Full historical inventory (per email)",
        "",
        "| Email | Principal | Total breaches |",
        "|---|---|---|",
    ]
    for email in sorted(all_breaches_by_email):
        principal = email_to_principal.get(email, "?")
        total = len(all_breaches_by_email[email])
        out.append(f"| {email} | {principal} | {total} |")
    out.append("")
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write report file or persist state; print to stdout.")
    parser.add_argument("--out-path", help="Override output path")
    args = parser.parse_args()

    api_key = os.environ.get("HIBP_API_KEY", "").strip()
    start = time.time()

    if not api_key:
        print(f"=== {SCRIPT_NAME} (tenant={args.tenant}) ===")
        print("skipped: HIBP_API_KEY env var not set. Set it to activate breach monitoring.")
        print("HIBP requires a paid subscription ($3.95/mo) for the breachedaccount endpoint;")
        print("see https://haveibeenpwned.com/API/Key.")
        emit_telemetry(SCRIPT_NAME, outcome="skipped",
                       reason="no_api_key",
                       duration_seconds=round(time.time() - start, 2))
        return 0

    tenant_cfg = load_tenant_cfg(args.tenant)
    vault = vault_path(tenant_cfg)
    email_pairs = collect_emails(tenant_cfg)
    if not email_pairs:
        print(f"=== {SCRIPT_NAME} ({args.tenant}) ===")
        print("no gmail addresses found in tenant config; nothing to check")
        emit_telemetry(SCRIPT_NAME, outcome="skipped",
                       reason="no_emails", duration_seconds=round(time.time() - start, 2))
        return 0

    email_to_principal = {e: p for e, p in email_pairs}
    state = load_state()
    new_breaches_by_email: dict[str, list[dict]] = {}
    all_breaches_by_email: dict[str, list[dict]] = {}
    api_errors = 0

    print(f"=== {SCRIPT_NAME} (tenant={args.tenant}) ===")
    print(f"checking {len(email_pairs)} email(s) against HIBP")
    for i, (email, principal) in enumerate(email_pairs):
        if i > 0:
            time.sleep(HIBP_MIN_INTERVAL_SECONDS)
        breaches, status = hibp_check_email(email, api_key)
        if status not in (200, 404):
            api_errors += 1
            print(f"  ! {email}: HTTP {status}")
            continue
        all_breaches_by_email[email] = breaches
        prev_names = set(state.get(email, []))
        new = [b for b in breaches if b.get("Name") not in prev_names]
        new_breaches_by_email[email] = new
        marker = "🚨" if new else "✓"
        print(f"  {marker} {email}: {len(breaches)} total, {len(new)} new")

    # Update state with current names
    new_state = dict(state)
    for email, breaches in all_breaches_by_email.items():
        new_state[email] = sorted({b.get("Name") for b in breaches if b.get("Name")})

    report = render_report(new_breaches_by_email, all_breaches_by_email, email_to_principal)
    new_total = sum(len(v) for v in new_breaches_by_email.values())

    if args.dry_run:
        print()
        print(report)
    else:
        # Always write a file when an API call was attempted (even if clean —
        # operators want to see the run happened). Use a stable per-day name.
        out_dir = vault / "HFO" / "OPSEC" / "Breach-Log"
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = Path(args.out_path) if args.out_path else (out_dir / f"{today}-breaches.md")
        out_path.write_text(report)
        print(f"\nwrote: {out_path}")
        save_state(new_state)

    emit_telemetry(SCRIPT_NAME, outcome="success" if not api_errors else "partial_failure",
                   emails_checked=len(email_pairs),
                   total_historical_breaches=sum(len(v) for v in all_breaches_by_email.values()),
                   new_breaches=new_total,
                   api_errors=api_errors,
                   duration_seconds=round(time.time() - start, 2))
    return 0 if not api_errors else 1


if __name__ == "__main__":
    sys.exit(main())
