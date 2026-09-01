from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.cli import cli
from hogli.manifest import REPO_ROOT
from hogli_commands.complexity_lint import WARN_AT, Finding, _python_findings

runner = CliRunner()


def _branchy_function(name: str, branches: int) -> str:
    checks = "".join(f"    if n == {i}:\n        return {i}\n" for i in range(branches))
    return f"def {name}(n: int) -> int:\n{checks}    return -1\n"


class TestComplexityLint:
    @pytest.mark.parametrize(
        ("branches", "name", "expected"),
        [
            pytest.param(9, "at_ten", [], id="at_threshold_not_reported"),
            pytest.param(11, "warns", [("warns", 12)], id="just_above_threshold_warns"),
            # No error tier: any complexity above the threshold is a warning only.
            pytest.param(16, "errors", [("errors", 17)], id="well_above_still_warns"),
        ],
    )
    def test_findings_above_threshold_are_warnings(self, tmp_path, branches: int, name: str, expected: list) -> None:
        # Complexity = branches + 1.
        target = tmp_path / "sample.py"
        target.write_text(_branchy_function(name, branches))

        findings = _python_findings([str(target)])

        assert [(f.name, f.complexity) for f in findings] == expected

    def test_cli_reports_warnings_without_failing(self, tmp_path) -> None:
        # The check is advisory: even a high-complexity finding must exit 0 and be
        # written to the --report file the CI report poster reads.
        finding = Finding(file="posthog/tasks/usage_report.py", line=1, column=1, name="f", complexity=17)
        report_path = tmp_path / "findings.json"
        with patch("hogli_commands.complexity_lint._python_findings", return_value=[finding]):
            result = runner.invoke(
                cli, ["lint:complexity", "posthog/tasks/usage_report.py", "--report", str(report_path)]
            )

        assert result.exit_code == 0
        assert "warning" in result.output
        assert "17" in result.output
        assert finding.name in report_path.read_text()

    @patch("hogli_commands.complexity_lint._python_findings", return_value=[])
    def test_only_scoped_files_are_checked(self, mock_findings: MagicMock) -> None:
        # Explicit paths outside posthog/ee/products (or deleted ones) must not reach ruff.
        # manage.py exists but sits outside PYTHON_SCOPE, so it exercises the scope filter
        # rather than the earlier is_file() check.
        result = runner.invoke(
            cli,
            [
                "lint:complexity",
                "posthog/tasks/usage_report.py",
                "manage.py",
                "posthog/deleted_file_does_not_exist.py",
            ],
        )
        assert result.exit_code == 0
        mock_findings.assert_called_once_with(["posthog/tasks/usage_report.py"])

    def test_thresholds_and_ci_contract_match_the_typescript_linter(self) -> None:
        # The mjs is invoked directly by ci-frontend.yml, so its threshold and its
        # --report flag (whose file the CI report poster reads) are pinned to the
        # Python side's contract.
        mjs = (REPO_ROOT / "bin" / "lint-complexity.mjs").read_text()
        assert f"const WARN_AT = {WARN_AT}\n" in mjs
        assert "indexOf('--report')" in mjs


class TestPreflightSoftCheck:
    @patch("hogli_commands.ci_preflight._emit_telemetry")
    @patch("hogli_commands.ci_preflight._staleness", return_value=("pass", "even with master", {}))
    @patch("hogli_commands.ci_preflight._fetch_master")
    @patch("hogli_commands.ci_preflight.shutil.which", return_value="/usr/bin/hogli")
    @patch("hogli_commands.ci_preflight.subprocess.run")
    @patch("hogli_commands.ci_preflight.changed_files", return_value=["frontend/src/scenes/sceneTypes.ts"])
    def test_warnings_surface_as_advisory_without_blocking_strict(
        self,
        mock_changed: MagicMock,
        mock_run: MagicMock,
        mock_which: MagicMock,
        mock_fetch: MagicMock,
        mock_stale: MagicMock,
        mock_emit: MagicMock,
    ) -> None:
        warning = "frontend/src/scenes/sceneTypes.ts:1:1: warning: `f` has cyclomatic complexity 12 (warn >10)"
        mock_run.return_value = MagicMock(returncode=0, stdout=warning + "\n", stderr="")
        result = runner.invoke(cli, ["ci:preflight", "--strict"])
        assert result.exit_code == 0
        assert "cyclomatic complexity 12" in result.output
        # Soft warnings are not CI failures — they must not trip the advisory footer.
        assert "unpushed CI failures" not in result.output
