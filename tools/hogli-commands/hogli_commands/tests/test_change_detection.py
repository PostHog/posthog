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
            _completed(stdout="file_branch.py\n"),
            _completed(stdout=" M file_modified.py\nA  file_staged.py\n?? file_untracked.py\n"),
        ]
        assert changed_files() == ["file_branch.py", "file_modified.py", "file_staged.py", "file_untracked.py"]

    @patch("hogli_commands.change_detection.subprocess.run")
    def test_deduplicates_across_diff_and_working_tree(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [_completed(stdout="same_file.py\n"), _completed(stdout="M  same_file.py\n")]
        assert changed_files() == ["same_file.py"]

    @patch("hogli_commands.change_detection.subprocess.run")
    def test_bad_ref_raises_instead_of_reporting_clean(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _completed(returncode=128, stderr="fatal: bad revision 'orgin/master'")
        with pytest.raises(click.UsageError):
            changed_files("orgin/master")


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
            ("x.py", [], False),
        ],
    )
    def test_matches(self, path: str, globs: list[str], expected: bool) -> None:
        assert matches_globs(path, globs) is expected
