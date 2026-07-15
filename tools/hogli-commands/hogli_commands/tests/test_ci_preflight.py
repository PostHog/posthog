from __future__ import annotations

import json

import pytest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.cli import cli
from hogli_commands.ci_preflight import _staleness_risks

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
    def test_strict_never_blocks_on_advisory(
        self, mock_changed: MagicMock, mock_fetch: MagicMock, mock_stale: MagicMock, mock_emit: MagicMock
    ) -> None:
        result = runner.invoke(cli, ["ci:preflight", "--strict"])
        assert "build:openapi" in result.output
        assert result.exit_code == 0

    @patch("hogli_commands.ci_preflight._emit_telemetry")
    @patch("hogli_commands.ci_preflight._staleness", return_value=("pass", "even with master", {}))
    @patch("hogli_commands.ci_preflight._fetch_master")
    @patch("hogli_commands.ci_preflight.shutil.which", return_value="/usr/bin/hogli")
    @patch("hogli_commands.ci_preflight.subprocess.run")
    @patch("hogli_commands.ci_preflight.changed_files", return_value=[".github/workflows/ci-foo.yml"])
    def test_strict_exits_nonzero_on_failure(
        self,
        mock_changed: MagicMock,
        mock_run: MagicMock,
        mock_which: MagicMock,
        mock_fetch: MagicMock,
        mock_stale: MagicMock,
        mock_emit: MagicMock,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="workflow convention violated", stderr="")
        result = runner.invoke(cli, ["ci:preflight", "--strict"])
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
        assert "run `hogli build:openapi` and commit before pushing" in result.output


class TestStalenessRisks:
    @pytest.mark.parametrize(
        "branch_files,master_files,conflicts,expected_fragments",
        [
            (["posthog/models/team.py"], ["frontend/src/lib/utils.tsx"], [], []),
            (["posthog/models/team.py"], ["frontend/src/lib/utils.tsx"], None, []),
            (["a.py"], ["b.py"], ["posthog/api/insight.py"], ["conflicts in 1 file"]),
            (
                ["posthog/migrations/0700_ours.py"],
                ["posthog/migrations/0700_theirs.py"],
                [],
                ["migrations added on both sides in posthog/migrations"],
            ),
            (["posthog/api/ours.py"], ["posthog/api/theirs.py"], [], ["master also changed build:openapi"]),
            (["a.py"], [".github/workflows/ci-backend.yml"], [], ["CI workflows changed on master (1 file(s))"]),
        ],
    )
    def test_risk_derivation(
        self,
        branch_files: list[str],
        master_files: list[str],
        conflicts: list[str] | None,
        expected_fragments: list[str],
    ) -> None:
        risks = _staleness_risks(branch_files, master_files, conflicts)
        assert len(risks) == len(expected_fragments)
        for fragment, risk in zip(expected_fragments, risks):
            assert fragment in risk
