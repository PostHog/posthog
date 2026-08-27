from __future__ import annotations

import json

import pytest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.cli import cli
from hogli_commands.ci_preflight import (
    COMPANION_CHECKS,
    DIFF_CHECKS,
    _pnpm_workspace_root,
    _run_workspace_scoped,
    _staleness_risks,
)

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

    @patch("hogli_commands.ci_preflight._emit_telemetry")
    @patch("hogli_commands.ci_preflight._staleness", return_value=("pass", "even with master", {}))
    @patch("hogli_commands.ci_preflight._fetch_master")
    @patch("hogli_commands.ci_preflight.subprocess.run")
    @patch("hogli_commands.ci_preflight.changed_files", return_value=["posthog/api/does_not_exist.py"])
    def test_nudge_names_the_command_without_running_it(
        self,
        mock_changed: MagicMock,
        mock_run: MagicMock,
        mock_fetch: MagicMock,
        mock_stale: MagicMock,
        mock_emit: MagicMock,
    ) -> None:
        result = runner.invoke(cli, ["ci:preflight", "--strict"])

        assert result.exit_code == 0
        assert "uv run mypy --cache-fine-grained ." in result.output
        # Giving the check a `verify` would tax every push with a repo-wide mypy run.
        ran = [arg for call in mock_run.call_args_list for arg in call.args[0]]
        assert "mypy" not in ran


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


class TestWorkspaceScopedLockfile:
    """The lockfile check must validate each pnpm workspace against its own lockfile.
    These hit the real repo layout, like TestDetectTestType in test_test_runner.py."""

    @pytest.mark.parametrize(
        "file_path,expected_workspace",
        [
            ("package.json", "."),
            ("frontend/package.json", "."),
            ("nodejs/package.json", "."),
            ("products/desktop/package.json", "products/desktop"),
            ("products/desktop/pnpm-lock.yaml", "products/desktop"),
            ("products/desktop/packages/core/package.json", "products/desktop"),
            # agent has a publish-only pnpm-lock.yaml but is a desktop workspace member
            ("products/desktop/packages/agent/package.json", "products/desktop"),
            ("tools/hedgebox-dummy/package.json", "tools/hedgebox-dummy"),
        ],
    )
    def test_workspace_root_resolution(self, file_path: str, expected_workspace: str) -> None:
        assert _pnpm_workspace_root(file_path) == expected_workspace

    @pytest.mark.parametrize(
        "changed,expected_dirs",
        [
            (["products/desktop/package.json"], ["products/desktop"]),
            (["package.json"], ["."]),
            (["package.json", "products/desktop/packages/core/package.json"], [".", "products/desktop"]),
        ],
    )
    @patch("hogli_commands.ci_preflight._workspace_install_present", return_value=True)
    @patch("hogli_commands.ci_preflight.shutil.which", return_value="/usr/bin/pnpm")
    @patch("hogli_commands.ci_preflight.subprocess.run")
    def test_lockfile_runs_once_per_workspace(
        self,
        mock_run: MagicMock,
        mock_which: MagicMock,
        mock_install: MagicMock,
        changed: list[str],
        expected_dirs: list[str],
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        lockfile = next(chk for chk in DIFF_CHECKS if chk.key == "lockfile")
        assert lockfile.workspace_scoped
        lockfile.matched = changed

        status, detail = _run_workspace_scoped(lockfile, do_fix=False)

        assert status == "pass"
        ran_dirs = [call.kwargs["cwd"] for call in mock_run.call_args_list]
        from hogli.manifest import REPO_ROOT

        assert ran_dirs == [REPO_ROOT if d == "." else REPO_ROOT / d for d in expected_dirs]

    @patch("hogli_commands.ci_preflight._workspace_install_present", return_value=True)
    @patch("hogli_commands.ci_preflight.shutil.which", return_value="/usr/bin/pnpm")
    @patch("hogli_commands.ci_preflight.subprocess.run")
    def test_lockfile_failure_names_the_workspace(
        self, mock_run: MagicMock, mock_which: MagicMock, mock_install: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="ERR_PNPM_OUTDATED_LOCKFILE", stderr="")
        lockfile = next(chk for chk in DIFF_CHECKS if chk.key == "lockfile")
        lockfile.matched = ["products/desktop/package.json"]

        status, detail = _run_workspace_scoped(lockfile, do_fix=False)

        assert status == "fail"
        assert "products/desktop: ERR_PNPM_OUTDATED_LOCKFILE" in detail

    @patch("hogli_commands.ci_preflight._workspace_install_present", return_value=False)
    def test_lockfile_skips_workspace_without_install(self, mock_install: MagicMock) -> None:
        lockfile = next(chk for chk in DIFF_CHECKS if chk.key == "lockfile")
        lockfile.matched = ["products/desktop/package.json"]

        status, detail = _run_workspace_scoped(lockfile, do_fix=False)

        assert status == "skipped"
        assert "products/desktop: needs node" in detail


class TestShadowDriftCompanion:
    @pytest.mark.parametrize(
        "changed,expected_exit,expected_fragment",
        [
            ([".github/workflows/ci-backend.yml"], 1, "mirror the change into .depot/workflows/ci-backend.yml"),
            ([".github/workflows/ci-backend.yml", ".depot/workflows/ci-backend.yml"], 0, "both files updated"),
            # Depot-only is a notice in CI, never a failure. Blocking it would false-block depot tuning.
            ([".depot/workflows/ci-backend.yml"], 0, ""),
            (
                [".github/actions/paths-filter/src/main.ts"],
                1,
                "mirror the change into .depot/actions/paths-filter/**",
            ),
            (
                [
                    ".github/actions/paths-filter/src/main.ts",
                    ".depot/actions/paths-filter/src/main.ts",
                ],
                0,
                "both files updated",
            ),
            ([".depot/actions/paths-filter/src/main.ts"], 0, "both files updated"),
        ],
    )
    @patch("hogli_commands.ci_preflight._emit_telemetry")
    @patch("hogli_commands.ci_preflight._staleness", return_value=("pass", "even with master", {}))
    @patch("hogli_commands.ci_preflight._fetch_master")
    @patch("hogli_commands.ci_preflight.shutil.which", return_value=None)
    def test_verdict_matches_ci(
        self,
        mock_which: MagicMock,
        mock_fetch: MagicMock,
        mock_stale: MagicMock,
        mock_emit: MagicMock,
        changed: list[str],
        expected_exit: int,
        expected_fragment: str,
    ) -> None:
        with patch("hogli_commands.ci_preflight.changed_files", return_value=changed):
            result = runner.invoke(cli, ["ci:preflight", "--strict"])

        assert result.exit_code == expected_exit
        if expected_fragment:
            assert expected_fragment in result.output
        else:
            assert "shadow-drift" not in result.output

    def test_pair_matches_workflow(self) -> None:
        import yaml
        from hogli.manifest import REPO_ROOT

        workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci-backend-shadow-drift.yml").read_text())
        # `on` parses as the boolean True in YAML 1.1.
        watched = set(workflow[True]["pull_request"]["paths"])
        companion_paths = {path for companion in COMPANION_CHECKS for path in (companion.source, companion.companion)}

        assert watched == companion_paths
