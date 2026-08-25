from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator

import pytest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.cli import cli

runner = CliRunner()

_BINARY = "/usr/local/bin/greptile"


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def _fake_greptile(
    status: int | dict[str, int] = 1, review_exit: int = 0, rev_list_exit: int = 0
) -> Callable[..., MagicMock]:
    """subprocess.run side effect: git rev-list, the config auth probe, status
    probes (one exit code, or one per commit), and the streamed review call."""

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        if cmd[0] == "git":
            return _proc(rev_list_exit, stdout="tip\nbase\n")
        if cmd[1] == "config":
            return _proc(0)
        if cmd[1:3] == ["review", "status"]:
            code = status if isinstance(status, int) else status[cmd[cmd.index("--commit") + 1]]
            return _proc(code, stdout="stored review\n")
        return _proc(review_exit)

    return fake_run


def _status_probes(mock_run: MagicMock) -> list[list[str]]:
    return [call.args[0] for call in mock_run.call_args_list if call.args[0][1:3] == ["review", "status"]]


def _reviews(mock_run: MagicMock) -> list[list[str]]:
    return [
        call.args[0]
        for call in mock_run.call_args_list
        if call.args[0][:2] == [_BINARY, "review"] and call.args[0][1:3] != ["review", "status"]
    ]


@pytest.fixture(autouse=True)
def greptile_on_path() -> Iterator[MagicMock]:
    with patch("hogli_commands.review.shutil.which", return_value=_BINARY) as mock_which:
        yield mock_which


class TestReview:
    def test_missing_cli_names_the_install_command(self, greptile_on_path: MagicMock) -> None:
        greptile_on_path.return_value = None
        result = runner.invoke(cli, ["review"])
        assert result.exit_code == 1
        assert "brew install greptileai/tap/greptile" in result.output

    @patch("hogli_commands.review.subprocess.run")
    def test_signed_out_exits_ex_config_without_starting_a_review(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _proc(1, stderr="error: not signed in. Set GREPTILE_API_KEY or run `greptile login`.")
        result = runner.invoke(cli, ["review"])
        assert result.exit_code == 78
        assert "greptile login" in result.output
        # The auth probe must be the only subprocess: a signed-out run may never
        # reach the paid review call.
        assert [call.args[0] for call in mock_run.call_args_list] == [[_BINARY, "config"]]

    @patch("hogli_commands.review.subprocess.run")
    def test_completed_review_is_reprinted_not_rebought(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_greptile(status=0)
        result = runner.invoke(cli, ["review"])
        assert result.exit_code == 0
        assert "stored review" in result.output
        assert _reviews(mock_run) == []

    @pytest.mark.parametrize(
        "status_exit,review_exit,expected_exit,expected_flag",
        [
            # An interrupted review is resumed, not restarted.
            (3, 0, 0, "--resume"),
            # No prior review: fresh run, and greptile's exit code passes through.
            (1, 4, 4, None),
        ],
    )
    @patch("hogli_commands.review.subprocess.run")
    def test_head_status_picks_the_review_call(
        self,
        mock_run: MagicMock,
        status_exit: int,
        review_exit: int,
        expected_exit: int,
        expected_flag: str | None,
    ) -> None:
        mock_run.side_effect = _fake_greptile(status=status_exit, review_exit=review_exit)
        result = runner.invoke(cli, ["review"])
        assert result.exit_code == expected_exit
        (review,) = _reviews(mock_run)
        if expected_flag is not None:
            assert expected_flag in review

    @patch("hogli_commands.review.subprocess.run")
    def test_force_skips_the_status_probe(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_greptile()
        result = runner.invoke(cli, ["review", "--force"])
        assert result.exit_code == 0
        assert _status_probes(mock_run) == []
        assert len(_reviews(mock_run)) == 1

    @pytest.mark.parametrize(
        "statuses,expected_exit,expected_probes",
        [
            ({"tip": 0, "base": 1}, 0, 1),  # tip reviewed: pass, and stop probing
            ({"tip": 1, "base": 0}, 0, 2),  # review ran earlier on the branch: still pass
            ({"tip": 3, "base": 1}, 1, 2),  # running or absent everywhere: no label
        ],
    )
    @patch("hogli_commands.review.subprocess.run")
    def test_check_passes_when_any_branch_commit_was_reviewed(
        self,
        mock_run: MagicMock,
        statuses: dict[str, int],
        expected_exit: int,
        expected_probes: int,
    ) -> None:
        mock_run.side_effect = _fake_greptile(status=statuses)
        result = runner.invoke(cli, ["review", "--check"])
        assert result.exit_code == expected_exit
        assert len(_status_probes(mock_run)) == expected_probes
        # --check must never fall through to a paid review.
        assert _reviews(mock_run) == []

    @patch("hogli_commands.review.subprocess.run")
    def test_check_falls_back_to_head_when_rev_list_fails(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = _fake_greptile(status=0, rev_list_exit=128)
        result = runner.invoke(cli, ["review", "--check"])
        assert result.exit_code == 0
        assert _status_probes(mock_run) == [[_BINARY, "review", "status", "--commit", "HEAD"]]

    @patch("hogli_commands.review.subprocess.run")
    def test_check_stops_walking_when_a_probe_hangs(self, mock_run: MagicMock) -> None:
        fake = _fake_greptile()

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            if cmd[1:3] == ["review", "status"]:
                raise subprocess.TimeoutExpired(cmd, 60)
            return fake(cmd, **kwargs)

        mock_run.side_effect = fake_run
        result = runner.invoke(cli, ["review", "--check"])
        # One timeout means they would all time out; a single 60s wait, not 20.
        assert result.exit_code == 1
        assert len(_status_probes(mock_run)) == 1

    @patch("hogli_commands.review.subprocess.run")
    def test_probe_failure_still_reviews(self, mock_run: MagicMock) -> None:
        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            if kwargs.get("capture_output"):
                raise subprocess.TimeoutExpired(cmd, 60)
            return _proc(0)

        mock_run.side_effect = fake_run
        result = runner.invoke(cli, ["review"])
        # A hung or broken probe must degrade to a plain review, not block it.
        assert result.exit_code == 0
        assert len(_reviews(mock_run)) == 1
