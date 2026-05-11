from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

from hogli_commands import hints


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.delenv("HOGLI_NO_HINTS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    state_path = tmp_path / "hogli_hints.json"
    with patch.object(hints, "_get_state_path", return_value=state_path):
        yield state_path


class TestRecordCheckRun:
    def test_creates_state_file(self, _isolated_state):
        hints.record_check_run("doctor:disk")
        state = json.loads(_isolated_state.read_text())
        assert "doctor:disk" in state["last_runs"]

    def test_updates_existing_state(self, _isolated_state):
        hints.record_check_run("doctor:disk")
        hints.record_check_run("doctor:zombies")
        state = json.loads(_isolated_state.read_text())
        assert "doctor:disk" in state["last_runs"]
        assert "doctor:zombies" in state["last_runs"]

    def test_overwrites_previous_timestamp(self, _isolated_state):
        hints.record_check_run("doctor")
        state1 = json.loads(_isolated_state.read_text())
        ts1 = state1["last_runs"]["doctor"]

        hints.record_check_run("doctor")
        state2 = json.loads(_isolated_state.read_text())
        ts2 = state2["last_runs"]["doctor"]

        assert ts2 >= ts1


class TestPickHint:
    def test_returns_hint_when_never_run(self):
        state: hints.HintsState = {}
        result = hints._pick_hint(state, datetime.now(UTC))
        assert result is not None
        assert "doctor:disk" in result

    def test_returns_none_when_all_recent(self):
        now = datetime.now(UTC)
        state: hints.HintsState = {
            "last_runs": {
                "doctor:disk": now.isoformat(),
                "doctor:zombies": now.isoformat(),
                "doctor": now.isoformat(),
            }
        }
        assert hints._pick_hint(state, now) is None

    @pytest.mark.parametrize(
        "stale_command, expected_fragment",
        [
            ("doctor:disk", "doctor:disk"),
            ("doctor:zombies", "doctor:zombies"),
            ("doctor", "hogli doctor"),
        ],
    )
    def test_returns_hint_when_stale(self, stale_command: str, expected_fragment: str):
        now = datetime.now(UTC)
        threshold = next(h.threshold_days for h in hints._HINT_DEFS if h.command == stale_command)
        all_commands = {"doctor:disk", "doctor:zombies", "doctor"}
        state: hints.HintsState = {
            "last_runs": {
                cmd: (now - timedelta(days=threshold + 1 if cmd == stale_command else 0)).isoformat()
                for cmd in all_commands
            }
        }
        result = hints._pick_hint(state, now)
        assert result is not None
        assert expected_fragment in result

    def test_priority_order_disk_first(self):
        now = datetime.now(UTC)
        state: hints.HintsState = {
            "last_runs": {
                "doctor:disk": (now - timedelta(days=8)).isoformat(),
                "doctor:zombies": (now - timedelta(days=8)).isoformat(),
                "doctor": (now - timedelta(days=15)).isoformat(),
            }
        }
        result = hints._pick_hint(state, now)
        assert result is not None
        assert "doctor:disk" in result


class TestMaybeShowHint:
    def test_suppressed_by_env_var(self, _isolated_state):
        with patch.dict("os.environ", {"HOGLI_NO_HINTS": "1"}):
            hints.maybe_show_hint("start")
        assert not _isolated_state.exists()

    def test_suppressed_in_ci(self, _isolated_state):
        with patch.dict("os.environ", {"CI": "true"}):
            hints.maybe_show_hint("start")
        assert not _isolated_state.exists()

    @pytest.mark.parametrize("command", sorted(hints._SKIP_COMMANDS))
    def test_suppressed_for_skip_commands(self, _isolated_state, command: str):
        hints.maybe_show_hint(command)
        assert not _isolated_state.exists()

    def test_rate_limited_within_24h(self, _isolated_state):
        now = datetime.now(UTC)
        state: hints.HintsState = {
            "last_hint_shown": now.isoformat(),
        }
        _isolated_state.write_text(json.dumps(state))

        with patch("click.secho") as mock_secho:
            hints.maybe_show_hint("start")
        mock_secho.assert_not_called()

    def test_shows_hint_after_24h(self, _isolated_state):
        old = datetime.now(UTC) - timedelta(hours=25)
        state: hints.HintsState = {
            "last_hint_shown": old.isoformat(),
        }
        _isolated_state.write_text(json.dumps(state))

        with patch("click.secho") as mock_secho:
            hints.maybe_show_hint("start")
        mock_secho.assert_called_once()
        call_args = mock_secho.call_args
        assert "Hint:" in call_args[0][0]

    def test_shows_hint_on_first_run(self, _isolated_state):
        with patch("click.secho") as mock_secho:
            hints.maybe_show_hint("start")
        mock_secho.assert_called_once()

    def test_updates_last_hint_shown(self, _isolated_state):
        with patch("click.secho"):
            hints.maybe_show_hint("start")
        state = json.loads(_isolated_state.read_text())
        assert "last_hint_shown" in state

    def test_never_raises(self, _isolated_state):
        with patch.object(hints, "_load_state", side_effect=RuntimeError("boom")):
            hints.maybe_show_hint("start")
