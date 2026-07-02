from __future__ import annotations

import json

from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.cli import cli

runner = CliRunner()


class TestKillSwitch:
    @patch("hogli_commands.ci_preflight._emit_telemetry")
    @patch("hogli_commands.ci_preflight.changed_files")
    def test_short_circuits_before_any_git_work(self, mock_changed: MagicMock, mock_emit: MagicMock) -> None:
        result = runner.invoke(cli, ["ci:preflight"], env={"HOGLI_PREFLIGHT_DISABLED": "1"})
        assert result.exit_code == 0
        assert "disabled" in result.output
        mock_changed.assert_not_called()
        assert mock_emit.call_args[0][0]["mode"] == "disabled"

    @patch("hogli_commands.ci_preflight._emit_telemetry")
    @patch("hogli_commands.ci_preflight.changed_files")
    def test_json_output_stays_parseable(self, mock_changed: MagicMock, mock_emit: MagicMock) -> None:
        result = runner.invoke(cli, ["ci:preflight", "--json"], env={"HOGLI_PREFLIGHT_DISABLED": "1"})
        assert result.exit_code == 0
        assert json.loads(result.output)["mode"] == "disabled"
        mock_changed.assert_not_called()


class TestStrictAndFixContracts:
    @patch("hogli_commands.ci_preflight._emit_telemetry")
    @patch("hogli_commands.ci_preflight._staleness", return_value=("pass", "even with master", {}))
    @patch("hogli_commands.ci_preflight._fetch_master")
    @patch("hogli_commands.ci_preflight.changed_files", return_value=["posthog/api/does_not_exist.py"])
    def test_strict_exits_nonzero_on_advisory(
        self, mock_changed: MagicMock, mock_fetch: MagicMock, mock_stale: MagicMock, mock_emit: MagicMock
    ) -> None:
        result = runner.invoke(cli, ["ci:preflight", "--strict"])
        assert "build:openapi" in result.output
        assert result.exit_code == 1

    @patch("hogli_commands.ci_preflight._emit_telemetry")
    @patch("hogli_commands.ci_preflight._capability_met", return_value=False)
    @patch("hogli_commands.ci_preflight._staleness", return_value=("pass", "even with master", {}))
    @patch("hogli_commands.ci_preflight._fetch_master")
    @patch("hogli_commands.ci_preflight.changed_files", return_value=["posthog/api/does_not_exist.py"])
    def test_fix_without_stack_still_advises_openapi(
        self,
        mock_changed: MagicMock,
        mock_fetch: MagicMock,
        mock_stale: MagicMock,
        mock_capability: MagicMock,
        mock_emit: MagicMock,
    ) -> None:
        result = runner.invoke(cli, ["ci:preflight", "--fix"])
        assert result.exit_code == 0
        assert "run `hogli build:openapi` and commit drift" in result.output
