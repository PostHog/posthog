"""Tests for the hogli build command."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.cli import cli
from hogli_commands.build import TRIGGERS, _get_changed_files, _match_commands

runner = CliRunner()


class TestTriggerMatching:
    @pytest.mark.parametrize(
        "path,expected_command",
        [
            ("frontend/src/queries/schema/index.ts", "build:schema"),
            ("frontend/src/queries/schema/schema-general.ts", "build:schema"),
            ("posthog/schema_migrations/0001_foo.py", "build:schema"),
            ("posthog/api/serializers.py", "build:openapi"),
            ("posthog/api/dashboard/views.py", "build:openapi"),
            ("posthog/scopes.py", "build:openapi"),
            ("ee/api/some_view.py", "build:openapi"),
            ("products/surveys/backend/api/serializers.py", "build:openapi"),
            ("products/surveys/backend/presentation/views.py", "build:openapi"),
            ("products/surveys/mcp/tools.yaml", "build:openapi"),
            ("services/mcp/definitions/core.yaml", "build:openapi"),
            ("posthog/hogql/grammar/HogQLParser.g4", "build:grammar"),
            ("posthog/taxonomy/taxonomy.py", "build:taxonomy-json"),
            ("products/surveys/frontend/src/Survey.tsx", "build:products"),
            ("products/posthog_ai/skills/foo/SKILL.md", "build:skills"),
            ("services/mcp/src/handlers/foo.ts", "build:schema-mcp"),
        ],
    )
    def test_file_triggers_expected_command(self, path: str, expected_command: str) -> None:
        assert expected_command in _match_commands({path})

    @pytest.mark.parametrize(
        "path",
        [
            "README.md",
            "posthog/models/team.py",
            "frontend/src/scenes/dashboard/Dashboard.tsx",
            ".github/workflows/ci.yml",
            "docker-compose.yml",
        ],
    )
    def test_unrelated_file_triggers_nothing(self, path: str) -> None:
        assert _match_commands({path}) == []

    def test_multiple_files_trigger_multiple_commands(self) -> None:
        changed = {
            "frontend/src/queries/schema/index.ts",
            "posthog/api/serializers.py",
            "posthog/hogql/grammar/HogQLParser.g4",
        }
        assert set(_match_commands(changed)) == {"build:schema", "build:openapi", "build:grammar"}

    def test_empty_changeset_triggers_nothing(self) -> None:
        assert _match_commands(set()) == []


class TestGetChangedFiles:
    @patch("hogli_commands.build.subprocess.check_output")
    def test_combines_branch_and_working_tree(self, mock_output: MagicMock) -> None:
        mock_output.side_effect = [
            "abc123\n",  # merge-base
            "file_branch.py\n",  # branch diff
            " M file_modified.py\nA  file_staged.py\n?? file_untracked.py\n",  # status --porcelain
        ]
        result = _get_changed_files()
        assert result == {"file_branch.py", "file_modified.py", "file_staged.py", "file_untracked.py"}

    @patch("hogli_commands.build.subprocess.check_output")
    def test_deduplicates_files(self, mock_output: MagicMock) -> None:
        mock_output.side_effect = [
            "abc123\n",
            "same_file.py\n",
            "M  same_file.py\n",  # same file in working tree
        ]
        result = _get_changed_files()
        assert result == {"same_file.py"}

    @patch("hogli_commands.build.subprocess.check_output")
    def test_handles_all_git_failures_gracefully(self, mock_output: MagicMock) -> None:
        from subprocess import CalledProcessError

        mock_output.side_effect = CalledProcessError(1, "git")
        result = _get_changed_files()
        assert result == set()


class TestBuildCommand:
    def test_list_shows_all_commands(self) -> None:
        result = runner.invoke(cli, ["build", "--list"])
        assert result.exit_code == 0
        for cmd in TRIGGERS:
            assert cmd in result.output

    @patch("hogli_commands.build._get_changed_files")
    def test_no_changes_exits_cleanly(self, mock_changed: MagicMock) -> None:
        mock_changed.return_value = set()
        result = runner.invoke(cli, ["build"])
        assert result.exit_code == 0
        assert "Nothing to rebuild" in result.output

    @patch("hogli_commands.build._get_changed_files")
    def test_unrelated_changes_exits_cleanly(self, mock_changed: MagicMock) -> None:
        mock_changed.return_value = {"README.md", "docs/foo.md"}
        result = runner.invoke(cli, ["build"])
        assert result.exit_code == 0
        assert "don't match any build trigger" in result.output

    @pytest.mark.parametrize(
        "changed_file,expected_command",
        [
            ("frontend/src/queries/schema/index.ts", "build:schema"),
            ("posthog/taxonomy/foo.py", "build:taxonomy-json"),
        ],
    )
    @patch("hogli_commands.build.subprocess.run")
    @patch("hogli_commands.build._get_changed_files")
    def test_smart_mode_runs_single_matching_pipeline(
        self, mock_changed: MagicMock, mock_run: MagicMock, changed_file: str, expected_command: str
    ) -> None:
        mock_changed.return_value = {changed_file}
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(cli, ["build"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        assert expected_command in mock_run.call_args[0][0]

    @patch("hogli_commands.build.subprocess.run")
    def test_force_runs_all(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(cli, ["build", "--force"])
        assert result.exit_code == 0
        assert mock_run.call_count == len(TRIGGERS)

    @patch("hogli_commands.build.subprocess.run")
    @patch("hogli_commands.build._get_changed_files")
    def test_dry_run_does_not_execute(self, mock_changed: MagicMock, mock_run: MagicMock) -> None:
        mock_changed.return_value = {"posthog/api/views.py"}
        result = runner.invoke(cli, ["build", "--dry-run"])
        assert result.exit_code == 0
        assert "build:openapi" in result.output
        mock_run.assert_not_called()

    @patch("hogli_commands.build.subprocess.run")
    def test_force_dry_run_lists_all(self, mock_run: MagicMock) -> None:
        result = runner.invoke(cli, ["build", "--force", "--dry-run"])
        assert result.exit_code == 0
        for cmd in TRIGGERS:
            assert cmd in result.output
        mock_run.assert_not_called()

    @patch("hogli_commands.build.subprocess.run")
    def test_continues_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [MagicMock(returncode=1)] + [MagicMock(returncode=0)] * (len(TRIGGERS) - 1)
        result = runner.invoke(cli, ["build", "--force"])
        assert result.exit_code == 1
        assert "failures" in result.output
        assert mock_run.call_count == len(TRIGGERS)
