"""Shared pure logic for the stamphog backtest harness.

Stdlib-only on purpose: the scripts that need heavy deps (claude-agent-sdk,
requests) import this module, never the other way around, so tests can import
it without the PEP 723 environments the scripts run under.
"""

from __future__ import annotations

import os
import re
import json
from collections import Counter
from pathlib import Path

# The reviewer prompt references the diff file the production run wrote into its
# checkout (an absolute runner path). Replay rewrites it to a local per-run copy.
DIFF_PATH_RE = re.compile(r"\S*\.pr-review-diff\S*\.patch")
RUN_DIR_RE = re.compile(r"^(?P<cohort>[^_]+)_(?P<arm>.+)_rep(?P<rep>\d+)$")

# Backtests tune the reviewer against this repo's norms only; other repos have
# different review conventions and their pull refs live on other remotes.
REPO = "PostHog/posthog"


def data_dir() -> Path:
    override = os.environ.get("STAMPHOG_BACKTEST_DATA")
    return Path(override) if override else Path(__file__).parent / "data"


def load_manifest(cohort: str | None = None, discretionary_only: bool = True) -> list[dict]:
    """Manifest rows for one cohort (a stamphog_version value, or 'unmarked')."""
    rows = []
    for line in (data_dir() / "manifest.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row.get("repo") != REPO:
            continue
        if cohort is not None and row.get("cohort") != cohort:
            continue
        if discretionary_only and row.get("gate_verdict") in ("DENIED", "AUTO-APPROVED"):
            continue
        if row.get("trace_id"):
            rows.append(row)
    rows.sort(key=lambda r: r["trace_id"])  # stable order so --limit slices deterministically
    return rows


def message_text(message: dict, drop_reminders: bool = False) -> str:
    """Join a message's text; optionally drop harness-injected <system-reminder> blocks.

    The Agent SDK re-injects fresh reminders (CLAUDE.md etc.) at replay time, so
    keeping the stored ones would double them up.
    """
    content = message.get("content", "")
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
    else:
        parts = [str(content)]
    if drop_reminders:
        parts = [p for p in parts if not p.lstrip().startswith("<system-reminder>")]
    return "\n".join(parts)


def split_trace_input(trace_path: Path) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) from a stored generation_1 input.

    Two instrumentation generations exist: traced-path runs store
    [system, user] with plain-string content; ai-gateway runs store block-list
    content with harness-injected reminder blocks. Gateway traces may lack a
    system message; callers fall back per arm.
    """
    messages = json.loads(trace_path.read_text())
    system = next((message_text(m) for m in messages if m.get("role") == "system"), "")
    user = next((message_text(m, drop_reminders=True) for m in messages if m.get("role") == "user"), "")
    if not user:
        raise ValueError(f"{trace_path.name}: no user message")
    return system, user


def rewrite_diff_path(user_prompt: str, diff_dst: Path) -> str:
    return DIFF_PATH_RE.sub(str(diff_dst), user_prompt)


def modal_verdict(results: list[dict]) -> str:
    return Counter(r["verdict"]["verdict"] for r in results).most_common(1)[0][0]


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:5.1f}%" if whole else "    -"
