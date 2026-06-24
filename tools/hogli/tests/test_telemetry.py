"""Tests for hogli telemetry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from unittest.mock import patch

from click.testing import CliRunner
from hogli import telemetry
from hogli.cli import _outcome, _should_track, cli

_TELEMETRY_ENV_VARS = (
    # Every CI marker the gate checks must be cleared, otherwise the suite
    # running on GitHub Actions (GITHUB_ACTIONS=1) would see telemetry disabled.
    *telemetry._CI_ENV_VARS,
    "POSTHOG_TELEMETRY_OPT_OUT",
    "DO_NOT_TRACK",
    "POSTHOG_TELEMETRY_HOST",
    "POSTHOG_TELEMETRY_API_KEY",
)


@pytest.fixture(autouse=True)
def telemetry_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(telemetry, "get_config_path", lambda: config_path)
    for var in _TELEMETRY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return config_path


def test_is_enabled_by_default():
    assert telemetry.is_enabled() is True


@pytest.mark.parametrize(
    "env_vars, config",
    [
        ({"POSTHOG_TELEMETRY_OPT_OUT": "1"}, {}),
        ({"DO_NOT_TRACK": "1"}, {}),
        ({"CI": "true"}, {}),
        ({"GITHUB_ACTIONS": "true"}, {}),
        ({"BUILDKITE": "true"}, {}),
        ({"GITLAB_CI": "true"}, {}),
        ({"POSTHOG_TELEMETRY_OPT_OUT": "1"}, {"enabled": True}),
    ],
)
def test_is_disabled(monkeypatch: pytest.MonkeyPatch, telemetry_config: Path, env_vars, config):
    if config:
        telemetry_config.write_text(json.dumps(config))
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    assert telemetry.is_enabled() is False


@pytest.mark.parametrize("ci_var", telemetry._CI_ENV_VARS)
def test_is_ci_detects_each_provider(monkeypatch: pytest.MonkeyPatch, ci_var: str):
    assert telemetry.is_ci() is False
    monkeypatch.setenv(ci_var, "true")
    assert telemetry.is_ci() is True


def test_is_disabled_when_no_api_key_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Standalone hogli users without a telemetry key get no-op telemetry by default."""

    class _FakeManifest:
        config: dict = {}

    monkeypatch.setattr(telemetry, "get_manifest", lambda: _FakeManifest())
    assert telemetry.is_enabled() is False


class TestAnonymousId:
    def test_stable_across_calls(self):
        first = telemetry.get_anonymous_id()
        second = telemetry.get_anonymous_id()
        assert first == second


class TestTrack:
    def test_queues_event_when_enabled(self, telemetry_config: Path):
        telemetry_config.write_text(
            json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True})
        )
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            telemetry.track("command_completed", {"command": "test"})
            telemetry.flush(timeout=1.0)
            mock_send.assert_called_once()
            batch = mock_send.call_args[0][0]
            assert len(batch) == 1
            assert batch[0]["event"] == "command_completed"
            assert batch[0]["distinct_id"] == "test-id"
            assert batch[0]["properties"]["command"] == "test"

    def test_uses_env_overrides(self, monkeypatch: pytest.MonkeyPatch, telemetry_config: Path):
        telemetry_config.write_text(
            json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True})
        )
        monkeypatch.setenv("POSTHOG_TELEMETRY_HOST", "http://localhost")
        monkeypatch.setenv("POSTHOG_TELEMETRY_API_KEY", "test-key")
        with patch("hogli.telemetry.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            telemetry.track("command_completed", {"command": "test"})
            telemetry.flush(timeout=2.0)
            mock_post.assert_called_once()
            assert mock_post.call_args[0][0] == "http://localhost/batch/"
            body = mock_post.call_args[1]["json"]
            assert body["api_key"] == "test-key"

    def test_noops_when_disabled(self, telemetry_config: Path):
        telemetry_config.write_text(json.dumps({"enabled": False}))
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            telemetry.track("command_completed")
            telemetry.flush(timeout=1.0)
            mock_send.assert_not_called()

    def test_noops_when_notice_not_shown(self, telemetry_config: Path):
        telemetry_config.write_text(json.dumps({"enabled": True, "anonymous_id": "test-id"}))
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            telemetry.track("command_completed")
            telemetry.flush(timeout=1.0)
            mock_send.assert_not_called()

    def test_flush_noop_when_queue_empty(self):
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            telemetry.flush(timeout=1.0)
            mock_send.assert_not_called()

    def test_flush_async_drains_queue_without_blocking(self, telemetry_config: Path):
        telemetry_config.write_text(
            json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True})
        )
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            telemetry.track("command_started", {"command": "test"})
            telemetry.flush_async()
            # The later blocking flush only joins the in-flight send; the queue
            # was already drained, so exactly one batch goes out.
            telemetry.flush(timeout=2.0)
            mock_send.assert_called_once()
            assert mock_send.call_args[0][0][0]["event"] == "command_started"


class TestFirstRunNotice:
    def test_creates_config(self, telemetry_config: Path):
        telemetry.show_first_run_notice_if_needed()
        assert telemetry_config.exists()
        config = json.loads(telemetry_config.read_text())
        assert config["enabled"] is True
        assert config["first_run_notice_shown"] is True
        assert "anonymous_id" in config

    def test_shown_once(self, telemetry_config: Path, capsys):
        telemetry.show_first_run_notice_if_needed()
        captured_first = capsys.readouterr()
        assert "hogli collects anonymous usage data" in captured_first.err

        # Second call should produce no output
        telemetry.show_first_run_notice_if_needed()
        captured_second = capsys.readouterr()
        assert captured_second.err == ""

    @pytest.mark.parametrize("ci_var", telemetry._CI_ENV_VARS)
    def test_suppressed_in_ci(self, monkeypatch: pytest.MonkeyPatch, telemetry_config: Path, capsys, ci_var: str):
        monkeypatch.setenv(ci_var, "true")
        telemetry.show_first_run_notice_if_needed()
        captured = capsys.readouterr()
        assert captured.err == ""
        assert not telemetry_config.exists()


class TestTelemetryCommands:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_telemetry_off(self, runner, telemetry_config: Path):
        result = runner.invoke(cli, ["telemetry:off"])
        assert result.exit_code == 0
        assert "disabled" in result.output.lower()
        config = json.loads(telemetry_config.read_text())
        assert config["enabled"] is False

    def test_telemetry_on(self, runner, telemetry_config: Path):
        telemetry_config.write_text(json.dumps({"enabled": False}))
        result = runner.invoke(cli, ["telemetry:on"])
        assert result.exit_code == 0
        config = json.loads(telemetry_config.read_text())
        assert config["enabled"] is True

    def test_telemetry_status_when_disabled_no_id_creation(self, runner, telemetry_config: Path):
        telemetry_config.write_text(json.dumps({"enabled": False, "first_run_notice_shown": True}))
        result = runner.invoke(cli, ["telemetry:status"])
        assert result.exit_code == 0
        assert "disabled" in result.output.lower()
        config = json.loads(telemetry_config.read_text())
        assert "anonymous_id" not in config


class TestInvokeTelemetry:
    def test_invoke_fires_started_and_completed_events(self, monkeypatch: pytest.MonkeyPatch, telemetry_config: Path):
        telemetry_config.write_text(
            json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True})
        )
        monkeypatch.setenv("POSTHOG_TELEMETRY_HOST", "http://localhost")
        monkeypatch.setenv("POSTHOG_TELEMETRY_API_KEY", "test-key")
        # The suite itself may run under `hogli test`, which marks its whole
        # process tree nested; pin the import-time capture for a stable assert.
        monkeypatch.setattr("hogli.cli._IS_NESTED", False)
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            runner = CliRunner()
            result = runner.invoke(cli, ["quickstart"])
            assert result.exit_code == 0

            # started is flushed eagerly in its own batch; completed flushes at
            # command end -- two sends, so a hard kill can't lose the started event.
            assert mock_send.call_count == 2
            batch = [event for call in mock_send.call_args_list for event in call.args[0]]
            events = {e["event"] for e in batch}
            assert "command_started" in events
            assert "command_completed" in events

            started = next(e for e in batch if e["event"] == "command_started")
            assert started["properties"]["command"] == "quickstart"
            assert "is_ci" in started["properties"]
            assert "hogli_version" in started["properties"]
            assert started["properties"]["is_nested"] is False

            completed = next(e for e in batch if e["event"] == "command_completed")
            assert completed["properties"]["command"] == "quickstart"
            assert completed["properties"]["exit_code"] == 0
            assert completed["properties"]["outcome"] == "success"
            assert "duration_s" in completed["properties"]
            assert "is_ci" in completed["properties"]

    def test_first_run_shows_notice_and_emits_events(self, monkeypatch: pytest.MonkeyPatch, telemetry_config: Path):
        """A brand-new install (no config file) must arm itself and emit events
        in the same invocation -- the notice block must run before the gate."""
        assert not telemetry_config.exists()
        monkeypatch.setenv("POSTHOG_TELEMETRY_HOST", "http://localhost")
        monkeypatch.setenv("POSTHOG_TELEMETRY_API_KEY", "test-key")
        monkeypatch.setattr("hogli.cli._IS_NESTED", False)
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            result = CliRunner().invoke(cli, ["quickstart"])
            assert result.exit_code == 0
            events = {e["event"] for call in mock_send.call_args_list for e in call.args[0]}
            assert events == {"command_started", "command_completed"}
        assert "hogli collects anonymous usage data" in result.output

    @pytest.mark.parametrize("command", ["telemetry:on", "telemetry:off", "telemetry:status"])
    def test_management_commands_emit_no_events(
        self, monkeypatch: pytest.MonkeyPatch, telemetry_config: Path, command: str
    ):
        telemetry_config.write_text(
            json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True})
        )
        monkeypatch.setenv("POSTHOG_TELEMETRY_HOST", "http://localhost")
        monkeypatch.setenv("POSTHOG_TELEMETRY_API_KEY", "test-key")
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            result = CliRunner().invoke(cli, [command])
            assert result.exit_code == 0
            mock_send.assert_not_called()


def _patch_cli_manifest(monkeypatch: pytest.MonkeyPatch, command_config: dict | None) -> None:
    """Point hogli.cli at a fake manifest whose every command has *command_config*.

    Keeps core tests off PostHog's hogli.yaml per the framework boundary.
    """

    class _FakeManifest:
        def command_flag(self, command, key):
            return bool((command_config or {}).get(key, False))

        def get_command_config(self, command):
            return command_config

    monkeypatch.setattr("hogli.cli.get_manifest", lambda: _FakeManifest())


class TestShouldTrack:
    @pytest.fixture(autouse=True)
    def _no_untracked_manifest(self, monkeypatch: pytest.MonkeyPatch):
        _patch_cli_manifest(monkeypatch, None)

    @pytest.mark.parametrize(
        "command, expected",
        [
            ("test", True),
            ("migrations:run", True),
            (None, False),
            ("telemetry:on", False),
            ("telemetry:off", False),
            ("telemetry:status", False),
            ("run", False),  # exec-replaces the process; events could never pair
        ],
    )
    def test_should_track(self, command, expected):
        assert _should_track(command) is expected

    def test_manifest_untracked_key_suppresses_tracking(self, monkeypatch: pytest.MonkeyPatch):
        _patch_cli_manifest(monkeypatch, {"untracked": True})
        assert _should_track("devbox:ssh") is False


class TestOutcome:
    @pytest.mark.parametrize(
        "exit_code, expected",
        [
            (0, "success"),
            (1, "error"),
            (2, "error"),
            (128, "error"),  # application-error idiom (e.g. git fatal), not a signal
            (130, "interrupted"),  # SIGINT (Ctrl-C)
            (143, "interrupted"),  # SIGTERM
            (-13, "interrupted"),  # subprocess killed by signal
        ],
    )
    def test_outcome(self, exit_code, expected):
        assert _outcome(exit_code) == expected
