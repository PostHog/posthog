"""Tests for auto-detecting test runner."""

from __future__ import annotations

from pathlib import Path

import pytest
from unittest.mock import patch

import click
from hogli_commands.test_runner import (
    _batch_find_rs_cfg_test,
    _detect_all,
    _find_test_files_for_source,
    _is_test_file,
    _parse_porcelain_path,
    _resolve_to_repo_relative,
    _run_changed,
    _run_grouped,
    detect_test_type,
)
from parameterized import parameterized


class TestDetectTestType:
    """Tests hit real files on disk — they validate that detection works
    end-to-end against the actual repo layout (package.json, Cargo.toml, go.mod).
    """

    @parameterized.expand(
        [
            ("posthog/api/test/test_user.py", "python", ["pytest", "-s", "posthog/api/test/test_user.py"]),
            ("posthog/models/test/test_team.py", "python", ["pytest", "-s", "posthog/models/test/test_team.py"]),
            ("ee/clickhouse/test/test_client.py", "python", ["pytest", "-s", "ee/clickhouse/test/test_client.py"]),
            (
                "products/alerts/backend/test/test_api.py",
                "python",
                ["pytest", "-s", "products/alerts/backend/test/test_api.py"],
            ),
            ("tools/hogli/tests/test_cli.py", "python", ["pytest", "-s", "tools/hogli/tests/test_cli.py"]),
            ("dags/tests/test_dag.py", "python", ["pytest", "-s", "dags/tests/test_dag.py"]),
        ]
    )
    def test_python_tests(self, file_path: str, expected_type: str, expected_command: list[str]) -> None:
        config = detect_test_type(file_path)
        assert config.test_type == expected_type
        assert config.command == expected_command
        assert "REDIS_URL" in config.env

    def test_python_with_node_id(self) -> None:
        config = detect_test_type("posthog/api/test/test_user.py::TestUserAPI::test_retrieve")
        assert config.test_type == "python"
        assert config.command == ["pytest", "-s", "posthog/api/test/test_user.py::TestUserAPI::test_retrieve"]

    def test_python_eval_uses_special_config(self) -> None:
        config = detect_test_type("ee/hogai/eval/eval_router.py")
        assert config.test_type == "python-eval"
        assert config.command == ["pytest", "-c", "ee/hogai/eval/pytest.ini", "-s", "ee/hogai/eval/eval_router.py"]
        assert "REDIS_URL" in config.env

    # -- Jest tests: these hit real package.json files on disk --

    @parameterized.expand(
        [
            ("frontend/src/scenes/dashboard/Dashboard.test.tsx", "@posthog/frontend"),
            ("frontend/src/lib/utils.test.ts", "@posthog/frontend"),
        ]
    )
    def test_frontend_jest(self, file_path: str, expected_filter: str) -> None:
        config = detect_test_type(file_path)
        assert config.test_type == "jest"
        assert config.command == ["pnpm", f"--filter={expected_filter}", "exec", "jest", file_path]

    def test_jest_node_id_adds_test_name_pattern(self) -> None:
        config = detect_test_type("frontend/src/lib/utils.test.ts::some test name")
        assert config.test_type == "jest"
        assert config.command == [
            "pnpm",
            "--filter=@posthog/frontend",
            "exec",
            "jest",
            "frontend/src/lib/utils.test.ts",
            "--testNamePattern",
            "some test name",
        ]

    def test_nodejs_jest(self) -> None:
        config = detect_test_type("nodejs/tests/cdp/cdp-api.test.ts")
        assert config.test_type == "jest"
        assert config.command[:4] == ["pnpm", "--filter=@posthog/nodejs", "exec", "jest"]

    @parameterized.expand(
        [
            ("common/hogvm/typescript/src/__tests__/execute.test.ts", "@posthog/hogvm"),
            ("common/replay-shared/src/replay.test.ts", "@posthog/replay-shared"),
            ("common/replay-headless/src/render.test.ts", "@posthog/replay-headless"),
        ]
    )
    def test_common_jest_packages(self, file_path: str, expected_filter: str) -> None:
        config = detect_test_type(file_path)
        assert config.test_type == "jest"
        assert config.command[:4] == ["pnpm", f"--filter={expected_filter}", "exec", "jest"]

    def test_playwright(self) -> None:
        config = detect_test_type("playwright/e2e/dashboards.spec.ts")
        assert config.test_type == "playwright"
        assert config.command == ["pnpm", "exec", "playwright", "test", "playwright/e2e/dashboards.spec.ts"]

    # -- Rust tests: these hit real Cargo.toml files on disk --

    def test_rust_workspace_crate(self) -> None:
        config = detect_test_type("rust/capture/tests/events.rs")
        assert config.test_type == "rust"
        assert "--manifest-path=rust/Cargo.toml" in config.command
        assert "-p" in config.command
        assert "capture" in config.command
        assert "--test" in config.command
        assert "events" in config.command

    def test_rust_standalone_cli(self) -> None:
        config = detect_test_type("cli/src/main.rs")
        assert config.test_type == "rust"
        assert "--manifest-path=cli/Cargo.toml" in config.command
        assert "--" not in config.command  # main.rs has no module filter

    def test_rust_standalone_funnel_udf(self) -> None:
        config = detect_test_type("funnel-udf/src/lib.rs")
        assert config.test_type == "rust"
        assert "--manifest-path=funnel-udf/Cargo.toml" in config.command
        assert "--" not in config.command  # lib.rs has no module filter

    def test_rust_single_file_filters_to_module(self) -> None:
        config = detect_test_type("cli/src/utils/throttler.rs")
        assert config.test_type == "rust"
        assert "--manifest-path=cli/Cargo.toml" in config.command
        assert config.command[-2:] == ["--", "utils::throttler"]

    def test_rust_directory_filters_to_module(self) -> None:
        config = detect_test_type("cli/src/utils")
        assert config.test_type == "rust"
        assert "--manifest-path=cli/Cargo.toml" in config.command
        assert config.command[-2:] == ["--", "utils"]

    def test_rust_node_id_filters_to_test(self) -> None:
        config = detect_test_type("cli/src/utils/throttler.rs::test_new_creates_empty_throttler")
        assert config.test_type == "rust"
        assert "--manifest-path=cli/Cargo.toml" in config.command
        assert config.command[-2:] == ["--", "utils::throttler::test_new_creates_empty_throttler"]

    def test_rust_no_cargo_toml_raises(self) -> None:
        with pytest.raises(click.UsageError, match="No Cargo.toml found"):
            detect_test_type("random/thing.rs")

    # -- Go tests: these hit real go.mod files on disk --
    # Any .go file or go.mod should run tests from the module root

    @parameterized.expand(
        [
            ("livestream/main_test.go", "livestream", "./..."),
            ("livestream/main.go", "livestream", "./..."),
            ("livestream/handlers/handler.go", "livestream", "./handlers/..."),
            ("livestream/go.mod", "livestream", "./..."),
            ("tools/phrocs/internal/tui/app_test.go", "tools/phrocs", "./internal/tui/..."),
            ("bin/hobby-installer/installer_test.go", "bin/hobby-installer", "./..."),
        ]
    )
    def test_go_tests(self, file_path: str, expected_mod_root: str, expected_target: str) -> None:
        config = detect_test_type(file_path)
        assert config.test_type == "go"
        assert config.command == ["go", "test", expected_target]
        assert config.cwd == _get_repo_root() / expected_mod_root

    def test_go_no_go_mod_raises(self) -> None:
        with pytest.raises(click.UsageError, match="No go.mod found"):
            detect_test_type("random/foo_test.go")

    # -- Directory tests: run all tests in a directory --

    @parameterized.expand(
        [
            ("posthog/api/test", "python", ["pytest", "-s", "posthog/api/test"]),
            ("ee/hogai", "python", ["pytest", "-s", "ee/hogai"]),
            (
                "tools/hogli-commands/hogli_commands/tests",
                "python",
                ["pytest", "-s", "tools/hogli-commands/hogli_commands/tests"],
            ),
        ]
    )
    def test_python_directory(self, dir_path: str, expected_type: str, expected_command: list[str]) -> None:
        config = detect_test_type(dir_path)
        assert config.test_type == expected_type
        assert config.command == expected_command

    def test_go_directory(self) -> None:
        config = detect_test_type("livestream")
        assert config.test_type == "go"
        assert config.command == ["go", "test", "./..."]
        assert config.cwd == _get_repo_root() / "livestream"

    def test_go_subdirectory(self) -> None:
        config = detect_test_type("livestream/events")
        assert config.test_type == "go"
        assert config.command == ["go", "test", "./events/..."]
        assert config.cwd == _get_repo_root() / "livestream"

    def test_rust_directory(self) -> None:
        config = detect_test_type("rust/capture/tests")
        assert config.test_type == "rust"
        assert "--manifest-path=rust/Cargo.toml" in config.command

    def test_jest_directory(self) -> None:
        config = detect_test_type("frontend/src/scenes/dashboard")
        assert config.test_type == "jest"
        assert config.command[:4] == ["pnpm", "--filter=@posthog/frontend", "exec", "jest"]

    def test_playwright_directory(self) -> None:
        config = detect_test_type("playwright/e2e")
        assert config.test_type == "playwright"
        assert config.command == ["pnpm", "exec", "playwright", "test", "playwright/e2e"]

    # -- Product directory (Turbo) tests --

    def test_product_root_uses_turbo(self) -> None:
        config = detect_test_type("products/alerts")
        assert config.test_type == "turbo"
        assert config.command == ["pnpm", "turbo", "run", "backend:test", "--filter=@posthog/products-alerts"]

    def test_product_root_trailing_slash_uses_turbo(self) -> None:
        config = detect_test_type("products/alerts/")
        assert config.test_type == "turbo"
        assert config.command == ["pnpm", "turbo", "run", "backend:test", "--filter=@posthog/products-alerts"]

    def test_product_subdirectory_uses_pytest(self) -> None:
        config = detect_test_type("products/error_tracking/backend/test")
        assert config.test_type == "python"
        assert config.command == ["pytest", "-s", "products/error_tracking/backend/test"]

    # -- Edge cases --

    def test_unknown_file_raises(self) -> None:
        with pytest.raises(click.UsageError, match="Could not detect test type"):
            detect_test_type("random/file.txt")

    def test_unknown_python_location_raises(self) -> None:
        with pytest.raises(click.UsageError, match="Could not detect test type"):
            detect_test_type("somewhere/test_foo.py")

    @patch("hogli_commands.test_runner.platform")
    def test_macos_env_var(self, mock_platform) -> None:
        mock_platform.system.return_value = "Darwin"
        config = detect_test_type("posthog/api/test/test_user.py")
        assert config.env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] == "YES"

    @patch("hogli_commands.test_runner.platform")
    def test_linux_no_objc_env_var(self, mock_platform) -> None:
        mock_platform.system.return_value = "Linux"
        config = detect_test_type("posthog/api/test/test_user.py")
        assert "OBJC_DISABLE_INITIALIZE_FORK_SAFETY" not in config.env


class TestResolveToRepoRelative:
    def test_relative_path_unchanged(self) -> None:
        with patch("hogli_commands.test_runner.Path.cwd", return_value=Path(str(_get_repo_root()))):
            result = _resolve_to_repo_relative("posthog/api/test/test_user.py")
            assert result == "posthog/api/test/test_user.py"

    def test_absolute_path_made_relative(self) -> None:
        repo_root = str(_get_repo_root())
        result = _resolve_to_repo_relative(f"{repo_root}/posthog/api/test/test_user.py")
        assert result == "posthog/api/test/test_user.py"

    def test_node_id_preserved(self) -> None:
        repo_root = str(_get_repo_root())
        result = _resolve_to_repo_relative(f"{repo_root}/posthog/test_foo.py::TestBar::test_baz")
        assert result == "posthog/test_foo.py::TestBar::test_baz"

    def test_relative_with_node_id(self) -> None:
        with patch("hogli_commands.test_runner.Path.cwd", return_value=Path(str(_get_repo_root()))):
            result = _resolve_to_repo_relative("posthog/test_foo.py::TestBar")
            assert result == "posthog/test_foo.py::TestBar"


class TestIsTestFile:
    @parameterized.expand(
        [
            ("posthog/api/test/test_user.py", True),
            ("ee/hogai/eval/eval_router.py", True),
            ("ee/hogai/eval_router.py", False),
            ("posthog/eval_something.py", False),
            ("ee/hogai/router.py", False),
            ("posthog/models/team.py", False),
            ("frontend/src/scenes/dashboard/Dashboard.test.tsx", True),
            ("frontend/src/scenes/dashboard/Dashboard.tsx", False),
            ("playwright/e2e/dashboards.spec.ts", True),
            ("playwright/e2e/helpers.ts", False),
            ("rust/capture/tests/events.rs", True),
            ("rust/capture/src/api_test.rs", True),
            ("livestream/main_test.go", True),
            ("livestream/main.go", False),
        ]
    )
    def test_is_test_file(self, path: str, expected: bool) -> None:
        assert _is_test_file(path) == expected

    @parameterized.expand(
        [
            ("rust/capture/src/api.rs",),
            ("rust/capture/src/v1/util.rs",),
        ]
    )
    def test_rs_inline_cfg_test_detected_with_batch(self, path: str) -> None:
        rs_cfg_test = _batch_find_rs_cfg_test("rust/capture/src")
        assert _is_test_file(path, rs_cfg_test=rs_cfg_test)

    def test_rs_inline_cfg_test_not_detected_without_batch(self) -> None:
        assert not _is_test_file("rust/capture/src/api.rs")

    def test_rs_inline_cfg_test_absent_from_batch(self) -> None:
        assert not _is_test_file("rust/capture/src/api.rs", rs_cfg_test=set())


class TestParsePorcelainPath:
    @parameterized.expand(
        [
            (" M posthog/api/views.py", "posthog/api/views.py"),
            ("?? posthog/new_file.py", "posthog/new_file.py"),
            ("A  posthog/added.py", "posthog/added.py"),
            ("R  old/test_foo.py -> new/test_foo.py", "new/test_foo.py"),
            ("C  src/a.py -> src/b.py", "src/b.py"),
            (' M "path with spaces/test_foo.py"', "path with spaces/test_foo.py"),
            ('R  "old name.py" -> "new name.py"', "new name.py"),
        ]
    )
    def test_parse_porcelain_path(self, line: str, expected: str) -> None:
        assert _parse_porcelain_path(line) == expected


class TestFindTestFilesForSource:
    @parameterized.expand(
        [
            ("posthog/api/comments.py", "posthog/api/test/test_comments.py"),
            (
                "tools/hogli-commands/hogli_commands/test_runner.py",
                "tools/hogli-commands/hogli_commands/tests/test_test_runner.py",
            ),
            (
                "frontend/src/scenes/dashboard/DashboardHeader.tsx",
                "frontend/src/scenes/dashboard/DashboardHeader.test.tsx",
            ),
            ("livestream/events/filter.go", "livestream/events/filter_test.go"),
        ]
    )
    def test_finds_test_for_source(self, source: str, expected_test: str) -> None:
        results = _find_test_files_for_source(source)
        assert expected_test in results

    def test_non_source_file_returns_empty(self) -> None:
        assert _find_test_files_for_source("README.md") == []

    def test_nonexistent_file_returns_empty(self) -> None:
        assert _find_test_files_for_source("posthog/api/nonexistent_module.py") == []


class TestRunChanged:
    @patch("hogli_commands.test_runner._run")
    @patch("hogli_commands.test_runner._get_changed_files")
    def test_runs_changed_python_files(self, mock_changed, mock_run) -> None:
        mock_changed.return_value = [
            "posthog/api/test/test_user.py",
            "posthog/api/test/test_comments.py",
            "posthog/api/views.py",  # not a test file
        ]
        _run_changed([])

        mock_run.assert_called_once()
        command = mock_run.call_args[0][0]
        assert command[0] == "pytest"
        assert "posthog/api/test/test_user.py" in command
        assert "posthog/api/test/test_comments.py" in command
        assert "posthog/api/views.py" not in command

    @patch("hogli_commands.test_runner._run")
    @patch("hogli_commands.test_runner._get_changed_files")
    def test_jest_files_grouped_by_package(self, mock_changed, mock_run) -> None:
        mock_changed.return_value = [
            "frontend/src/scenes/dashboard/Dashboard.test.tsx",
            "frontend/src/lib/utils.test.ts",
            "nodejs/tests/cdp/cdp-api.test.ts",
        ]
        _run_changed([])

        assert mock_run.call_count == 2
        commands = [call[0][0] for call in mock_run.call_args_list]
        # One call for @posthog/frontend, one for @posthog/nodejs
        frontend_cmd = next(c for c in commands if "--filter=@posthog/frontend" in c)
        nodejs_cmd = next(c for c in commands if "--filter=@posthog/nodejs" in c)
        assert "frontend/src/scenes/dashboard/Dashboard.test.tsx" in frontend_cmd
        assert "frontend/src/lib/utils.test.ts" in frontend_cmd
        assert "nodejs/tests/cdp/cdp-api.test.ts" in nodejs_cmd

    @patch("hogli_commands.test_runner._run")
    @patch("hogli_commands.test_runner._get_changed_files")
    def test_discovers_tests_for_changed_source_files(self, mock_changed, mock_run) -> None:
        mock_changed.return_value = ["posthog/api/comments.py"]
        _run_changed([])

        mock_run.assert_called_once()
        command = mock_run.call_args[0][0]
        assert "posthog/api/test/test_comments.py" in command

    @patch("hogli_commands.test_runner._run")
    @patch("hogli_commands.test_runner._get_changed_files")
    def test_deduplicates_direct_and_discovered_tests(self, mock_changed, mock_run) -> None:
        mock_changed.return_value = [
            "posthog/api/comments.py",
            "posthog/api/test/test_comments.py",
        ]
        _run_changed([])

        mock_run.assert_called_once()
        command = mock_run.call_args[0][0]
        assert command.count("posthog/api/test/test_comments.py") == 1

    @patch("hogli_commands.test_runner._get_changed_files")
    def test_no_changed_files_exits(self, mock_changed) -> None:
        mock_changed.return_value = ["posthog/api/views.py"]
        with pytest.raises(SystemExit):
            _run_changed([])

    @patch("hogli_commands.test_runner._get_changed_files")
    def test_changed_on_master_raises(self, mock_changed) -> None:
        mock_changed.side_effect = click.UsageError("Cannot use --changed on the master branch.")
        with pytest.raises(click.UsageError, match="master"):
            _run_changed([])


class TestRunGrouped:
    @patch("hogli_commands.test_runner._run")
    def test_mixed_python_and_jest(self, mock_run) -> None:
        detected = _detect_all(
            [
                "posthog/api/test/test_user.py",
                "frontend/src/scenes/dashboard/Dashboard.test.tsx",
            ]
        )
        _run_grouped(detected, [])
        assert mock_run.call_count == 2
        commands = [call[0][0] for call in mock_run.call_args_list]
        python_cmd = next(c for c in commands if c[0] == "pytest")
        jest_cmd = next(c for c in commands if c[0] == "pnpm")
        assert "posthog/api/test/test_user.py" in python_cmd
        assert "frontend/src/scenes/dashboard/Dashboard.test.tsx" in jest_cmd

    @patch("hogli_commands.test_runner._run")
    def test_passes_extra_args(self, mock_run) -> None:
        detected = _detect_all(["posthog/api/test/test_user.py"])
        _run_grouped(detected, ["-v", "--tb=short"])
        command = mock_run.call_args[0][0]
        assert "-v" in command
        assert "--tb=short" in command

    @patch("hogli_commands.test_runner._run")
    def test_jest_grouped_by_package(self, mock_run) -> None:
        detected = _detect_all(
            [
                "frontend/src/scenes/dashboard/Dashboard.test.tsx",
                "frontend/src/lib/utils.test.ts",
                "nodejs/tests/cdp/cdp-api.test.ts",
            ]
        )
        _run_grouped(detected, [])
        assert mock_run.call_count == 2
        commands = [call[0][0] for call in mock_run.call_args_list]
        frontend_cmd = next(c for c in commands if "--filter=@posthog/frontend" in c)
        nodejs_cmd = next(c for c in commands if "--filter=@posthog/nodejs" in c)
        assert "frontend/src/scenes/dashboard/Dashboard.test.tsx" in frontend_cmd
        assert "frontend/src/lib/utils.test.ts" in frontend_cmd
        assert "nodejs/tests/cdp/cdp-api.test.ts" in nodejs_cmd


def _get_repo_root():
    from hogli.manifest import REPO_ROOT

    return REPO_ROOT
