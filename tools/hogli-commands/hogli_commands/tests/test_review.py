from __future__ import annotations

import subprocess

import pytest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.cli import cli

runner = CliRunner()

_BINARY = "/usr/local/bin/greptile"


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


class TestReview:
    @patch("hogli_commands.review.shutil.which", return_value=None)
    def test_missing_cli_names_the_install_command(self, mock_which: MagicMock) -> None:
        result = runner.invoke(cli, ["review"])
        assert result.exit_code == 1
        assert "brew install greptileai/tap/greptile" in result.output

    @patch("hogli_commands.review.subprocess.run")
    @patch("hogli_commands.review.shutil.which", return_value=_BINARY)
    def test_signed_out_exits_ex_config_without_starting_a_review(
        self, mock_which: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = _proc(1, stderr="error: not signed in. Set GREPTILE_API_KEY or run `greptile login`.")
        result = runner.invoke(cli, ["review"])
        assert result.exit_code == 78
        assert "greptile login" in result.output
        # The auth probe must be the only subprocess: a signed-out run may never
        # reach the paid review call.
        assert [call.args[0] for call in mock_run.call_args_list] == [[_BINARY, "config"]]

    @pytest.mark.parametrize(
        "argv,status_exit,review_exit,expected_exit,expect_status_probe,expected_review_flag",
        [
            # A completed review for HEAD is re-printed, never re-bought.
            (["review"], 0, None, 0, True, None),
            # An interrupted review is resumed, not restarted.
            (["review"], 3, 0, 0, True, "--resume"),
            # No prior review: fresh run, and greptile's exit code passes through.
            (["review"], 1, 4, 4, True, None),
            # --force skips the status probe and always starts fresh.
            (["review", "--force"], None, 0, 0, False, None),
        ],
    )
    @patch("hogli_commands.review.subprocess.run")
    @patch("hogli_commands.review.shutil.which", return_value=_BINARY)
    def test_reviews_head_once(
        self,
        mock_which: MagicMock,
        mock_run: MagicMock,
        argv: list[str],
        status_exit: int | None,
        review_exit: int | None,
        expected_exit: int,
        expect_status_probe: bool,
        expected_review_flag: str | None,
    ) -> None:
        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            if cmd[1] == "config":
                return _proc(0)
            if cmd[1:3] == ["review", "status"]:
                return _proc(status_exit if status_exit is not None else 1, stdout="stored review\n")
            return _proc(review_exit if review_exit is not None else 0)

        mock_run.side_effect = fake_run
        result = runner.invoke(cli, argv)

        assert result.exit_code == expected_exit
        commands = [call.args[0] for call in mock_run.call_args_list]
        status_probes = [cmd for cmd in commands if cmd[1:3] == ["review", "status"]]
        reviews = [cmd for cmd in commands if cmd[1] == "review" and "status" not in cmd]
        assert bool(status_probes) == expect_status_probe
        if status_exit == 0:
            assert reviews == []
            assert "stored review" in result.output
        else:
            assert len(reviews) == 1
            if expected_review_flag is not None:
                assert expected_review_flag in reviews[0]

    @pytest.mark.parametrize(
        "status_exit,expected_exit",
        [
            (0, 0),  # completed review at HEAD: safe to skip the bot
            (1, 1),  # no review
            (3, 1),  # review still running counts as not reviewed
        ],
    )
    @patch("hogli_commands.review.subprocess.run")
    @patch("hogli_commands.review.shutil.which", return_value=_BINARY)
    def test_check_gates_on_a_completed_head_review(
        self, mock_which: MagicMock, mock_run: MagicMock, status_exit: int, expected_exit: int
    ) -> None:
        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            if cmd[1] == "config":
                return _proc(0)
            return _proc(status_exit)

        mock_run.side_effect = fake_run
        result = runner.invoke(cli, ["review", "--check"])

        assert result.exit_code == expected_exit
        # --check must never fall through to a paid review.
        reviews = [call.args[0] for call in mock_run.call_args_list if call.args[0][1:2] == ["review"]]
        assert reviews == [[_BINARY, "review", "status", "--commit", "HEAD"]]

    @patch("hogli_commands.review.subprocess.run")
    @patch("hogli_commands.review.shutil.which", return_value=_BINARY)
    def test_probe_failure_still_reviews(self, mock_which: MagicMock, mock_run: MagicMock) -> None:
        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            if kwargs.get("capture_output"):
                raise subprocess.TimeoutExpired(cmd, 60)
            return _proc(0)

        mock_run.side_effect = fake_run
        result = runner.invoke(cli, ["review"])
        # A hung or broken probe must degrade to a plain review, not block it.
        assert result.exit_code == 0
        assert any(call.args[0][1] == "review" for call in mock_run.call_args_list)
