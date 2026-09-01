from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from unittest.mock import MagicMock, call, patch

from click.testing import CliRunner
from hogli.cli import cli
from hogli.manifest import REPO_ROOT
from hogli_commands.complexity_lint import TEST_WARN_AT, WARN_AT, Finding, _python_findings, is_test_file

runner = CliRunner()


def _branchy_function(name: str, branches: int) -> str:
    checks = "".join(f"    if n == {i}:\n        return {i}\n" for i in range(branches))
    return f"def {name}(n: int) -> int:\n{checks}    return -1\n"


def _ts_branchy_function(branches: int) -> str:
    checks = "".join(f"    if (n === {i}) return {i}\n" for i in range(branches))
    return f"export function probe(n: number): number {{\n{checks}    return -1\n}}\n"


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

    @pytest.mark.parametrize(
        ("branches", "expected"),
        [
            pytest.param(11, [], id="above_production_limit_below_test_limit"),
            pytest.param(16, [("f", 17, TEST_WARN_AT)], id="above_test_limit_warns"),
        ],
    )
    def test_findings_use_the_given_threshold(self, tmp_path, branches: int, expected: list) -> None:
        # Complexity = branches + 1. The max_complexity argument must reach ruff's config.
        target = tmp_path / "test_sample.py"
        target.write_text(_branchy_function("f", branches))

        findings = _python_findings([str(target)], max_complexity=TEST_WARN_AT)

        assert [(f.name, f.complexity, f.limit) for f in findings] == expected

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            pytest.param("posthog/api/insight.py", False, id="production_module"),
            pytest.param("posthog/api/insight.test.py", False, id="dot_test_suffix_is_not_a_convention_here"),
            pytest.param("posthog/api/test_insight.py", True, id="colocated_test_prefix"),
            pytest.param("posthog/api/test/test_insight.py", True, id="test_package"),
            pytest.param("products/tasks/backend/tests/test_agent.py", True, id="tests_package"),
            pytest.param("posthog/conftest.py", True, id="conftest"),
            pytest.param(
                "posthog/clickhouse/migrations/0097_v2_test.py", False, id="_test_suffix_is_migration_not_test"
            ),
        ],
    )
    def test_is_test_file(self, path: str, expected: bool) -> None:
        assert is_test_file(path) is expected

    def test_cli_reports_warnings_without_failing(self, tmp_path) -> None:
        # The check is advisory: even a high-complexity finding must exit 0 and be
        # written to the --report file the CI report poster reads.
        finding = Finding(
            file="posthog/tasks/usage_report.py", line=1, column=1, name="f", complexity=17, limit=WARN_AT
        )
        report_path = tmp_path / "findings.json"
        with patch("hogli_commands.complexity_lint._python_findings", return_value=[finding]):
            result = runner.invoke(
                cli, ["lint:complexity", "posthog/tasks/usage_report.py", "--report", str(report_path)]
            )

        assert result.exit_code == 0
        assert "warning" in result.output
        assert "17" in result.output
        assert "warn >10" in result.output
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
        mock_findings.assert_called_once_with(["posthog/tasks/usage_report.py"], max_complexity=WARN_AT)

    @patch("hogli_commands.complexity_lint._python_findings", return_value=[])
    def test_test_files_are_linted_at_the_relaxed_threshold(self, mock_findings: MagicMock) -> None:
        # Test and production files go to ruff in separate runs, one per limit.
        result = runner.invoke(
            cli,
            ["lint:complexity", "posthog/tasks/usage_report.py", "posthog/api/test/test_activity_log.py"],
        )
        assert result.exit_code == 0
        assert mock_findings.call_args_list == [
            call(["posthog/tasks/usage_report.py"], max_complexity=WARN_AT),
            call(["posthog/api/test/test_activity_log.py"], max_complexity=TEST_WARN_AT),
        ]


_MJS = REPO_ROOT / "bin" / "lint-complexity.mjs"
_TS_LINTABLE = shutil.which("node") is not None and (REPO_ROOT / "frontend" / "node_modules" / "typescript").is_dir()


@pytest.mark.skipif(not _TS_LINTABLE, reason="needs node and frontend/node_modules/typescript")
class TestTypeScriptLinterContract:
    # The mjs runs directly in ci-frontend.yml, so the Python suite owns its contract
    # coverage. Skipped where frontend dependencies are absent (backend CI shards).
    def _run_mjs(self, target, *flags: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["node", str(_MJS), *flags, str(target)], cwd=REPO_ROOT, capture_output=True, text=True)

    @pytest.mark.parametrize(
        ("filename", "branches", "expected_limit"),
        [
            pytest.param("probe.ts", 11, WARN_AT, id="production_file_at_12_warns"),
            pytest.param("probe.test.ts", 11, None, id="test_file_at_12_passes"),
            pytest.param("probe.test.ts", 16, TEST_WARN_AT, id="test_file_at_17_warns"),
        ],
    )
    def test_limit_depends_on_file_kind(
        self, tmp_path, filename: str, branches: int, expected_limit: int | None
    ) -> None:
        target = tmp_path / filename
        target.write_text(_ts_branchy_function(branches))

        findings = json.loads(self._run_mjs(target, "--json").stdout)

        assert [f["limit"] for f in findings] == ([expected_limit] if expected_limit is not None else [])

    def test_bare_invocation_reports_the_first_file(self, tmp_path) -> None:
        # ci-frontend.yml passes --report and hogli passes --json, both leading flags.
        # A bare invocation must not drop the first file argument.
        target = tmp_path / "probe.ts"
        target.write_text(_ts_branchy_function(11))

        result = self._run_mjs(target)

        assert result.returncode == 0
        assert "warning" in result.stdout
        assert "warn >10" in result.stdout


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
