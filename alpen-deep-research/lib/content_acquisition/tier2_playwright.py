#!/usr/bin/env python3
"""Tier 2 PDF acquisition via real Chrome (winnie-chrome via CDP).

Single callable entry point: ``fetch_pdf_tier2(url, output_path)``.

Replaces the prose protocol previously inlined in
``alpen-deep-research/skills/content-acquisition/SKILL.md`` for the Tier 2
escalation path. The structural fix is dispatch-to-script: agents call ONE
function, the function does the protocol (CDP connect, navigate, magic-byte
validate, escalate or return).

Setup requirement (NOT auto-installed):
    The ``playwright`` Python package is NOT in either of the existing venvs
    (``~/Winnie/rag/venv`` or ``~/Winnie/alpen-platform/.venv``) as of
    2026-05-07. Before first use install with:

        ~/Winnie/rag/venv/bin/pip install playwright

    The browser binary is NOT needed because we connect over CDP to the
    persistent ``io.howardfamily.ops.winnie-chrome`` daemon already running
    at ``http://localhost:9222`` (see ~/Winnie/CLAUDE.md browser-scheduled
    pipeline). So ``playwright install`` is unnecessary.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Common publisher "download PDF" button text/selectors. Order matters:
# more specific patterns first.
PDF_BUTTON_SELECTORS: list[str] = [
    "a:has-text('Download PDF')",
    "a:has-text('Full Text PDF')",
    "a:has-text('Full-Text PDF')",
    "a:has-text('PDF')",
    "button:has-text('Download PDF')",
    "a[href*='.pdf']",
    "a[data-track-action*='pdf' i]",
]

NETWORK_IDLE_EXTRA_WAIT_S: float = 5.0  # let Cloudflare interstitials settle
NAV_TIMEOUT_MS: int = 60_000


def _has_pdf_magic_bytes(path: Path) -> bool:
    """Return True iff the file at ``path`` has the %PDF magic header.

    Tries ``file(1)`` first for libmagic-quality detection, falls back to a
    direct first-4-byte check.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    file_bin = shutil.which("file")
    if file_bin:
        try:
            out = subprocess.run(
                [file_bin, str(path)], capture_output=True, text=True, timeout=10
            )
            if "PDF document" in out.stdout:
                return True
            # If `file` reported something else (HTML, etc.), trust it.
            if out.returncode == 0 and out.stdout:
                return False
        except (subprocess.TimeoutExpired, OSError):
            pass
    # Fallback: raw bytes
    try:
        with path.open("rb") as fh:
            head = fh.read(4)
        return head.startswith(b"%PDF")
    except OSError:
        return False


def _classify_paywall(body_text: str | None) -> bool:
    if not body_text:
        return False
    needles = (
        "subscribe to access",
        "purchase access",
        "sign in to read",
        "access through your institution",
        "this article is available to subscribers",
    )
    lower = body_text.lower()
    return any(n in lower for n in needles)


async def _fetch_pdf_async(
    url: str, output_path: Path, cdp_endpoint: str
) -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError:
        return {
            "status": "failed-network",
            "magic_bytes_pdf": False,
            "bytes_downloaded": 0,
            "final_url": url,
            "error": (
                "playwright python package not installed. Install with: "
                "~/Winnie/rag/venv/bin/pip install playwright"
            ),
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    final_url = url
    bytes_downloaded = 0
    error: str | None = None
    body_text: str | None = None

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.connect_over_cdp(cdp_endpoint)
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "failed-network",
                "magic_bytes_pdf": False,
                "bytes_downloaded": 0,
                "final_url": url,
                "error": f"CDP connect failed at {cdp_endpoint}: {exc!r}",
            }

        # Use existing default context (winnie-chrome holds auth).
        contexts = browser.contexts
        ctx = contexts[0] if contexts else await browser.new_context()
        page = await ctx.new_page()

        try:
            response = await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="load")
            try:
                await page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
            except Exception:  # noqa: BLE001
                pass  # some sites never go fully idle; press on
            await asyncio.sleep(NETWORK_IDLE_EXTRA_WAIT_S)

            if response is not None:
                final_url = response.url
                content_type = (response.headers or {}).get("content-type", "")
            else:
                content_type = ""

            # Direct PDF response (Content-Type or .pdf URL): pull the body.
            if "application/pdf" in content_type or final_url.lower().endswith(".pdf"):
                try:
                    if response is not None:
                        body = await response.body()
                        tmp_path.write_bytes(body)
                        bytes_downloaded = len(body)
                except Exception as exc:  # noqa: BLE001
                    error = f"direct PDF body read failed: {exc!r}"

            # Otherwise, look for a publisher download button.
            if bytes_downloaded == 0:
                try:
                    body_text = await page.inner_text("body", timeout=5_000)
                except Exception:  # noqa: BLE001
                    body_text = None

                clicked = False
                for selector in PDF_BUTTON_SELECTORS:
                    try:
                        loc = page.locator(selector).first
                        if await loc.count() == 0:
                            continue
                        async with page.expect_download(timeout=30_000) as dl_info:
                            await loc.click(timeout=10_000)
                        download = await dl_info.value
                        await download.save_as(str(tmp_path))
                        if tmp_path.exists():
                            bytes_downloaded = tmp_path.stat().st_size
                        clicked = True
                        break
                    except Exception:  # noqa: BLE001
                        continue
                if not clicked and bytes_downloaded == 0 and not error:
                    error = "no PDF response or download button found"

        except Exception as exc:  # noqa: BLE001
            error = f"navigation failed: {exc!r}"
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass

    # Magic-byte validation + atomic move.
    is_pdf = _has_pdf_magic_bytes(tmp_path) if tmp_path.exists() else False
    if is_pdf:
        tmp_path.replace(output_path)
        return {
            "status": "ok",
            "magic_bytes_pdf": True,
            "bytes_downloaded": bytes_downloaded,
            "final_url": final_url,
            "error": None,
        }

    # Decide failure mode.
    if tmp_path.exists() and tmp_path.stat().st_size > 0 and _classify_paywall(body_text):
        try:
            tmp_path.unlink()
        except OSError:
            pass
        return {
            "status": "failed-paywall",
            "magic_bytes_pdf": False,
            "bytes_downloaded": bytes_downloaded,
            "final_url": final_url,
            "error": error or "paywall detected in body text",
        }
    if tmp_path.exists():
        try:
            tmp_path.unlink()
        except OSError:
            pass
    if bytes_downloaded > 0:
        return {
            "status": "failed-content-mismatch",
            "magic_bytes_pdf": False,
            "bytes_downloaded": bytes_downloaded,
            "final_url": final_url,
            "error": error or "downloaded bytes did not have PDF magic header",
        }
    return {
        "status": "failed-network",
        "magic_bytes_pdf": False,
        "bytes_downloaded": 0,
        "final_url": final_url,
        "error": error or "no bytes downloaded",
    }


def fetch_pdf_tier2(
    url: str, output_path: str, cdp_endpoint: str = "http://localhost:9222"
) -> dict[str, Any]:
    """Tier 2 PDF acquisition via real Chrome (winnie-chrome via CDP).

    Args:
        url: Source URL for the PDF (or publisher landing page that links one).
        output_path: Absolute filesystem path where the validated PDF is
            written. Atomic: ``<output_path>.tmp`` is used during transfer and
            only promoted to ``output_path`` after magic-byte validation.
        cdp_endpoint: Chrome DevTools Protocol endpoint. Default targets the
            local ``winnie-chrome`` daemon documented in
            ``~/Winnie/CLAUDE.md``.

    Returns:
        Dict with keys: ``status`` (one of ``ok``,
        ``failed-content-mismatch``, ``failed-network``, ``failed-paywall``),
        ``magic_bytes_pdf`` (bool), ``bytes_downloaded`` (int),
        ``final_url`` (str), ``error`` (str or None).
    """
    return asyncio.run(_fetch_pdf_async(url, Path(output_path), cdp_endpoint))


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Tier 2 PDF acquisition via winnie-chrome (CDP)."
    )
    parser.add_argument("--url", required=True, help="Source URL for the PDF")
    parser.add_argument(
        "--output", required=True, help="Absolute path where the PDF will be written"
    )
    parser.add_argument(
        "--cdp",
        default="http://localhost:9222",
        help="CDP endpoint (default: http://localhost:9222)",
    )
    args = parser.parse_args()

    result = fetch_pdf_tier2(args.url, args.output, args.cdp)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
