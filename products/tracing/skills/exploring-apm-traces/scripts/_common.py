"""Shared helpers for the exploring-apm-traces skill scripts.

When a script runs as `python3 scripts/foo.py FILE`, Python prepends the script's
directory to sys.path, so `from _common import ...` resolves without any setup.
"""

import json


SPAN_KIND = {0: "Unspecified", 1: "Internal", 2: "Server", 3: "Client", 4: "Producer", 5: "Consumer"}
STATUS_CODE = {0: "Unset", 1: "OK", 2: "Error"}


def is_zero_id(s):
    return not s or set(s) == {"0"}


def unwrap_text_envelope(raw):
    # Claude Code persists large MCP tool results as [{"type": "text", "text": "<json>"}].
    if isinstance(raw, list) and raw and isinstance(raw[0], dict) and raw[0].get("type") == "text":
        return json.loads(raw[0]["text"])
    return raw


def load_trace_file(path):
    with open(path) as f:
        raw = json.load(f)
    raw = unwrap_text_envelope(raw)
    if isinstance(raw, dict):
        for key in ("trace_spans", "spans", "results"):
            if key in raw and isinstance(raw[key], list):
                return raw[key]
        return [raw]
    return raw if isinstance(raw, list) else [raw]


def fmt_duration(nanos):
    if nanos is None:
        return "?"
    try:
        n = int(nanos)
    except (TypeError, ValueError):
        return str(nanos)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}s"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}ms"
    if n >= 1_000:
        return f"{n / 1_000:.1f}\u00b5s"
    return f"{n}ns"


def truncate(s, max_len, show_total=False):
    if max_len <= 0 or len(s) <= max_len:
        return s
    suffix = f"... [{len(s)} chars total]" if show_total else "..."
    return s[:max_len] + suffix


def is_root(span):
    if span.get("is_root_span"):
        return True
    parent = span.get("parent_span_id") or ""
    return is_zero_id(parent)
