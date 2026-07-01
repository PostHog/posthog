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
