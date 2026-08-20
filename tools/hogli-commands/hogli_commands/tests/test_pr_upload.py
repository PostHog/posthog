from __future__ import annotations

import subprocess
from collections.abc import Iterator
from subprocess import CompletedProcess

import pytest
from unittest.mock import patch

from hogli_commands import pr_upload, upload_image

_KIND = upload_image._KIND


@pytest.fixture
def gh_installed() -> Iterator[None]:
    with patch.object(pr_upload.shutil, "which", return_value="/usr/bin/gh"):
        yield


def _gh_returns(stdout: str, returncode: int = 0) -> CompletedProcess[str]:
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_explicit_pr_is_used_without_consulting_gh() -> None:
    # --pr must not pay for a network call, and must win over whatever branch you are on.
    with patch.object(pr_upload.subprocess, "run") as run:
        assert pr_upload.commit_message(_KIND, 78999) == "add screenshot for posthog#78999"
    run.assert_not_called()


def test_detected_pr_is_named_in_the_message(gh_installed: None) -> None:
    with patch.object(pr_upload.subprocess, "run", return_value=_gh_returns("78999\n")):
        assert pr_upload.commit_message(_KIND, None) == "add screenshot for posthog#78999"


@pytest.mark.parametrize(
    "outcome",
    [
        {"return_value": _gh_returns("", returncode=1)},
        {"return_value": _gh_returns("not a number\n")},
        {"return_value": _gh_returns("\n")},
        {"side_effect": subprocess.TimeoutExpired(cmd="gh", timeout=10)},
        {"side_effect": OSError("gh exploded")},
    ],
    ids=["no_open_pr", "unparseable", "empty", "timed_out", "spawn_failed"],
)
def test_detection_failure_leaves_the_plain_message(gh_installed: None, outcome: dict[str, object]) -> None:
    # Screenshots often land before `gh pr create`, so no detection failure may block an
    # upload or leak a half-built reference like "for posthog#None".
    with patch.object(pr_upload.subprocess, "run", **outcome):
        assert pr_upload.commit_message(_KIND, None) == "add screenshot"


def test_missing_gh_leaves_the_plain_message() -> None:
    with patch.object(pr_upload.shutil, "which", return_value=None):
        assert pr_upload.commit_message(_KIND, None) == "add screenshot"
