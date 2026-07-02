from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

import click
from hogli_commands.change_detection import changed_files, matches_globs


def _completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> MagicMock:
    return MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)


class TestChangedFiles:
    @patch("hogli_commands.change_detection.subprocess.run")
    def test_combines_branch_diff_and_working_tree(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed(stdout="file_branch.py\0"),
            _completed(stdout=" M file_modified.py\0A  file_staged.py\0?? file_untracked.py\0"),
        ]
        assert changed_files() == ["file_branch.py", "file_modified.py", "file_staged.py", "file_untracked.py"]

    @patch("hogli_commands.change_detection.subprocess.run")
    def test_deduplicates_across_diff_and_working_tree(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [_completed(stdout="same_file.py\0"), _completed(stdout="M  same_file.py\0")]
        assert changed_files() == ["same_file.py"]

    @patch("hogli_commands.change_detection.subprocess.run")
    def test_paths_with_spaces_stay_unquoted(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed(stdout="posthog/migrations/0067_table copy.py\0"),
            _completed(stdout=" M docs/a b.md\0"),
        ]
        assert changed_files() == ["docs/a b.md", "posthog/migrations/0067_table copy.py"]

    @patch("hogli_commands.change_detection.subprocess.run")
    def test_default_base_falls_back_to_local_master(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed(returncode=128, stderr="fatal: bad revision 'origin/master...HEAD'"),
            _completed(stdout="file_branch.py\0"),
            _completed(stdout=""),
        ]
        assert changed_files() == ["file_branch.py"]

    @patch("hogli_commands.change_detection.subprocess.run")
    def test_no_base_ref_degrades_to_working_tree_only(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed(returncode=128, stderr="fatal: bad revision"),
            _completed(returncode=128, stderr="fatal: bad revision"),
            _completed(stdout="?? sandbox_edit.py\0"),
        ]
        assert changed_files() == ["sandbox_edit.py"]

    @patch("hogli_commands.change_detection.subprocess.run")
    def test_explicit_bad_ref_raises_instead_of_reporting_clean(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(returncode=128, stderr="fatal: bad revision 'orgin/master'")
        with pytest.raises(click.UsageError):
            changed_files("orgin/master")

    @patch("hogli_commands.change_detection.subprocess.run")
    def test_status_failure_raises_instead_of_dropping_uncommitted_work(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            _completed(stdout="file_branch.py\0"),
            _completed(returncode=128, stderr="fatal: Unable to create index.lock"),
        ]
        with pytest.raises(click.UsageError):
            changed_files()


class TestMatchesGlobs:
    @pytest.mark.parametrize(
        "path,globs,expected",
        [
            ("posthog/api/insight.py", ["posthog/api/*"], True),
            ("posthog/api/dashboards/dashboard.py", ["posthog/api/*"], True),
            ("posthog/models/team.py", ["posthog/api/*"], False),
            ("tools/a/b.py", ["*.py"], True),
            ("notes.md", ["*.py"], False),
            ("posthog/migrations/0001_x.py", ["*/migrations/*.py"], True),
            ("pnpm-workspace.yaml", ["pnpm-workspace.yaml"], True),
            ("patches/dayjs@1.11.11.patch", ["patches/*"], True),
            ("x.py", [], False),
        ],
    )
    def test_matches(self, path: str, globs: list[str], expected: bool) -> None:
        assert matches_globs(path, globs) is expected
