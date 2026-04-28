"""Lightweight Jinja2-style template renderer for Alpen Platform composers.

Resolves {{namespace.field}} variables in markdown templates using a
context dict. Unresolved variables are left in place AND collected for
reporting (so the composer can ask the user about them).

Why not Jinja2? Because we want UNRESOLVED variables to remain visible
in the output (to surface to the user), not error out. Jinja2's
StrictUndefined errors and Undefined silently substitutes empty string —
neither is what we want. So this is a deliberately minimal renderer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w.-]*)\s*\}\}")


@dataclass
class RenderResult:
    text: str
    resolved: dict[str, str]
    unresolved: list[str]


def _walk(context: dict, dotted_key: str) -> object | None:
    """Navigate context['a']['b']['c'] for 'a.b.c'. Returns None on miss."""
    parts = dotted_key.split(".")
    cur = context
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def render(template: str, context: dict) -> RenderResult:
    """Substitute {{ns.field}} variables. Unresolved left as-is.

    Numeric fields named *.value or *.fee or *.amount or *.spent or
    *.remaining or *_total are formatted as $X,XXX automatically (USD).
    """
    resolved: dict[str, str] = {}
    unresolved: list[str] = []

    def replace(match: re.Match) -> str:
        key = match.group(1)
        val = _walk(context, key)
        if val is None:
            if key not in unresolved:
                unresolved.append(key)
            return match.group(0)
        # Money formatting for fields that look like fees / values
        last = key.split(".")[-1]
        money_suffixes = {"value", "fee", "amount", "spent", "remaining", "total", "billed"}
        if (
            last.endswith("_total") or last in money_suffixes
            or any(last.endswith(f"_{s}") for s in money_suffixes)
        ) and isinstance(val, (int, float)):
            formatted = f"${val:,.0f}"
        elif isinstance(val, list):
            formatted = ", ".join(str(v) for v in val)
        else:
            formatted = str(val)
        resolved[key] = formatted
        return formatted

    text = VAR_RE.sub(replace, template)
    return RenderResult(text=text, resolved=resolved, unresolved=unresolved)


def collect_variables(template: str) -> list[str]:
    """Return unique variable names used in template, in order of first
    appearance. Used by composers to detect missing inputs before
    starting the user dialogue."""
    seen, out = set(), []
    for m in VAR_RE.finditer(template):
        k = m.group(1)
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out
