from __future__ import annotations

import math

import pytest

import click
from hogli_commands.worktrees import _parse_cutoff

_NOW = 1_700_000_000.0


class TestParseCutoff:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self, monkeypatch):
        monkeypatch.setattr("hogli_commands.worktrees.time.time", lambda: _NOW)

    @pytest.mark.parametrize(
        ("value", "expected_offset"),
        [
            ("30s", 30),
            ("15m", 15 * 60),
            ("3h", 3 * 3600),
            ("7d", 7 * 86400),
            ("2w", 2 * 604800),
        ],
        ids=["seconds", "minutes", "hours", "days", "weeks"],
    )
    def test_interval_subtracts_from_now(self, value, expected_offset) -> None:
        cutoff, _ = _parse_cutoff(value)
        assert cutoff == _NOW - expected_offset

    def test_all_includes_everything(self) -> None:
        cutoff, _ = _parse_cutoff("all")
        assert cutoff == math.inf

    def test_iso_date_uses_local_timestamp(self) -> None:
        from datetime import datetime

        cutoff, _ = _parse_cutoff("2026-06-01")
        assert cutoff == datetime(2026, 6, 1).timestamp()

    @pytest.mark.parametrize("value", ["nonsense", "7", "d7", "3 days", ""])
    def test_invalid_input_rejected(self, value) -> None:
        with pytest.raises(click.BadParameter):
            _parse_cutoff(value)
