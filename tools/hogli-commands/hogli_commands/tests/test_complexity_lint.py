from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.cli import cli
from hogli.manifest import REPO_ROOT
from hogli_commands.complexity_lint import ERROR_AT, WARN_AT, _python_findings

runner = CliRunner()


def _branchy_function(name: str, branches: int) -> str:
    checks = "".join(f"    if n == {i}:\n        return {i}\n" for i in range(branches))
    return f"def {name}(n: int) -> int:\n{checks}    return -1\n"


class TestComplexityLint:
    def test_ruff_findings_classify_warning_and_error(self, tmp_path) -> None:
        # Complexity = branches + 1: 11 branches → 12 (warning), 16 branches → 17 (error).
        target = tmp_path / "sample.py"
        target.write_text(_branchy_function("warns", 11) + _branchy_function("errors", 16))

        findings = sorted(_python_findings([str(target)]), key=lambda f: f.line)

        assert [(f.name, f.complexity, f.severity) for f in findings] == [
            ("warns", 12, "warning"),
            ("errors", 17, "error"),
        ]

    def test_at_thresholds_is_not_reported(self, tmp_path) -> None:
        # 10 is the warn threshold, not yet a warning.
        target = tmp_path / "sample.py"
        target.write_text(_branchy_function("at_ten", 9))

        assert _python_findings([str(target)]) == []

    @patch("hogli_commands.complexity_lint._python_findings", return_value=[])
    def test_only_scoped_files_are_checked(self, mock_findings: MagicMock) -> None:
        # Explicit paths outside posthog/ee/products (or deleted ones) must not reach ruff.
        result = runner.invoke(
            cli,
            [
                "lint:complexity",
                "posthog/tasks/usage_report.py",
                "nodejs/src/main.py",
                "posthog/deleted_file_does_not_exist.py",
            ],
        )
        assert result.exit_code == 0
        mock_findings.assert_called_once_with(["posthog/tasks/usage_report.py"])

    def test_thresholds_match_the_typescript_linter(self) -> None:
        # The mjs is invoked directly by ci-frontend.yml, so it declares its own
        # thresholds — this pins them to the Python side's.
        mjs = (REPO_ROOT / "bin" / "lint-complexity.mjs").read_text()
        assert f"const WARN_AT = {WARN_AT}\n" in mjs
        assert f"const ERROR_AT = {ERROR_AT}\n" in mjs


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
        warning = (
            "frontend/src/scenes/sceneTypes.ts:1:1 warning: `f` has cyclomatic complexity 12 (warn >10, error >15)"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=warning + "\n", stderr="")
        result = runner.invoke(cli, ["ci:preflight", "--strict"])
        assert result.exit_code == 0
        assert "cyclomatic complexity 12" in result.output
        # Soft warnings are not CI failures — they must not trip the advisory footer.
        assert "unpushed CI failures" not in result.output
