"""Pytest adapter for the test quarantine (schema contract: ``core``).

Applies markers to collected items that match an active pytest entry:
``mode: run`` → ``xfail(strict=False)`` so the test still executes and its
duration/outcome keep flowing to the JUnit→OTLP pipeline; ``mode: skip`` →
``skip`` for hangs, import-time flakes, and state-polluters.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hogli_commands.quarantine import core


def apply_quarantine_markers(items: list[pytest.Item], path: Path | None = None) -> None:
    """Mark quarantined items. Fail-open: any problem with the quarantine file
    is reported on stderr and quarantine is disabled — collection never breaks.

    Idempotent via the ``quarantine`` guard marker: the conftest hook registers
    twice in runs where ``products/conftest.py`` or ``ee/conftest.py``
    star-import ``posthog/conftest.py`` alongside it.
    """
    try:
        result = core.load(path or core.QUARANTINE_PATH)
        for message in result.errors:
            sys.stderr.write(f"[quarantine] disabled entry: {message}\n")
        entries = core.active_entries(result.entries, runner="pytest", today=core.today_utc())
        if not entries:
            return
        for item in items:
            if item.get_closest_marker("quarantine") is not None:
                continue
            entry = core.find_match(entries, item.nodeid)
            if entry is None:
                continue
            reason = f"quarantined until {entry.expires.isoformat()}: {entry.reason} ({entry.issue or entry.owner})"
            item.add_marker(pytest.mark.quarantine)
            if entry.mode == "skip":
                item.add_marker(pytest.mark.skip(reason=reason))
            else:
                item.add_marker(pytest.mark.xfail(reason=reason, strict=False))
    except Exception as exc:
        sys.stderr.write(f"[quarantine] disabled: {exc}\n")
