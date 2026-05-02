"""Post-command contextual hints for hogli CLI.

Occasionally reminds developers to run maintenance commands like
``hogli doctor``, ``hogli doctor:disk``, etc.

Suppression:
    HOGLI_NO_HINTS=1  -> disable hints
    CI=*              -> disable hints (same as telemetry)

State file: ~/.config/posthog/hogli_hints.json
"""

from __future__ import annotations

import os
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

import click

# Commands that should never trigger a trailing hint
_SKIP_COMMANDS = frozenset(
    {
        "doctor",
        "doctor:disk",
        "doctor:zombies",
        "telemetry:off",
        "telemetry:on",
        "telemetry:status",
        "meta:check",
        "meta:concepts",
        "help",
        "quickstart",
    }
)


class _HintDef:
    __slots__ = ("command", "threshold_days", "message")

    def __init__(self, command: str, threshold_days: int, message: str) -> None:
        self.command = command
        self.threshold_days = threshold_days
        self.message = message


_HINT_DEFS: tuple[_HintDef, ...] = (
    _HintDef("doctor:disk", 7, "Run `hogli doctor:disk` to check for disk bloat"),
    _HintDef("doctor:zombies", 7, "Run `hogli doctor:zombies` to find orphaned processes"),
    _HintDef("doctor", 14, "Run `hogli doctor` for a quick health check"),
)


# ---------------------------------------------------------------------------
# State persistence (mirrors telemetry.py pattern)
# ---------------------------------------------------------------------------


class HintsState(TypedDict, total=False):
    last_hint_shown: str  # ISO 8601
    last_runs: dict[str, str]  # command -> ISO 8601


def _get_state_path() -> Path:
    return Path.home() / ".config" / "posthog" / "hogli_hints.json"


def _load_state() -> HintsState:
    try:
        return json.loads(_get_state_path().read_text())
    except Exception:
        return HintsState()


def _save_state(state: HintsState) -> None:
    try:
        path = _get_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_check_run(command: str) -> None:
    """Record that a doctor command was run (updates hint cooldown)."""
    state = _load_state()
    last_runs = state.get("last_runs", {})
    last_runs[command] = datetime.now(UTC).isoformat()
    state["last_runs"] = last_runs
    _save_state(state)


def maybe_show_hint(command: str | None) -> None:
    """Evaluate triggers and maybe print a hint to stderr. Never raises."""
    try:
        _maybe_show_hint(command)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _maybe_show_hint(command: str | None) -> None:
    if os.environ.get("HOGLI_NO_HINTS") == "1":
        return
    if os.environ.get("CI"):
        return
    if command in _SKIP_COMMANDS:
        return

    state = _load_state()
    now = datetime.now(UTC)

    # Rate limit: max 1 hint per 24 hours
    last_shown = state.get("last_hint_shown")
    if last_shown:
        try:
            last_dt = datetime.fromisoformat(last_shown)
            if now - last_dt < timedelta(hours=24):
                return
        except (ValueError, TypeError):
            pass

    hint = _pick_hint(state, now)
    if hint is None:
        return

    click.secho(f"\n  Hint: {hint}", fg="bright_black", err=True)

    state["last_hint_shown"] = now.isoformat()
    _save_state(state)


def _pick_hint(state: HintsState, now: datetime) -> str | None:
    """Return the first applicable hint message, or None."""
    last_runs = state.get("last_runs", {})

    for hint_def in _HINT_DEFS:
        last_run = last_runs.get(hint_def.command)
        if last_run is None:
            return hint_def.message
        try:
            last_dt = datetime.fromisoformat(last_run)
            if now - last_dt > timedelta(days=hint_def.threshold_days):
                return hint_def.message
        except (ValueError, TypeError):
            return hint_def.message

    return None
