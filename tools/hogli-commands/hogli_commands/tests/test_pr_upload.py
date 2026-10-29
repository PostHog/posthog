from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from unittest.mock import patch

import click
from click.testing import CliRunner
from hogli_commands import pr_assets, pr_upload, upload_image, upload_video

_KIND = upload_image._KIND
_GH = "/usr/bin/gh"


@pytest.fixture
def gh_installed() -> Iterator[None]:
    with patch.object(pr_upload.shutil, "which", return_value=_GH):
        yield


def _gh_returns(stdout: str, returncode: int = 0) -> CompletedProcess[str]:
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


@pytest.mark.parametrize(("pr", "expected"), [(78999, "add screenshot for posthog#78999"), (None, "add screenshot")])
def test_commit_message_names_only_the_pr_number(pr: int | None, expected: str) -> None:
    assert pr_upload.commit_message(_KIND, pr) == expected


def test_detected_pr_is_parsed(gh_installed: None) -> None:
    with patch.object(pr_upload.subprocess, "run", return_value=_gh_returns("78999\n")):
        assert pr_upload._open_pull_request() == 78999


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
def test_detection_failure_means_no_pr(gh_installed: None, outcome: dict[str, object]) -> None:
    # Screenshots often land before `gh pr create`, so no detection failure may block an
    # upload or leak a half-built reference like "for posthog#None".
    with patch.object(pr_upload.subprocess, "run", **outcome):
        assert pr_upload._open_pull_request() is None


def test_missing_gh_means_no_pr() -> None:
    with patch.object(pr_upload.shutil, "which", return_value=None):
        assert pr_upload._open_pull_request() is None


@pytest.mark.parametrize(
    ("command", "filename", "caption_args", "attach_suffix"),
    [
        (upload_image.upload_image, "after.png", ["--alt", "after fix"], "#after fix"),
        (upload_video.upload_video, "demo.mp4", ["--label", "demo"], ""),
    ],
    ids=["image_keeps_alt", "video_drops_label"],
)
def test_open_pr_and_attach_capable_gh_edit_the_pr_description(
    tmp_path: Path, command: click.Command, filename: str, caption_args: list[str], attach_suffix: str
) -> None:
    # gh rejects alt text on video, so a label forwarded as `#label` would fail the upload.
    path = tmp_path / filename
    path.write_bytes(b"fake bytes")
    with (
        patch.object(pr_upload, "_gh_with_attach", return_value=_GH),
        patch.object(pr_upload, "github_token", return_value="personal-token"),
        patch.object(pr_upload.subprocess, "run", return_value=_gh_returns("")) as run,
        patch.object(pr_upload.telemetry, "add_command_properties") as add_props,
        patch.object(pr_assets, "publish") as publish,
    ):
        result = CliRunner(mix_stderr=False).invoke(command, ["--yes", "--pr", "1234", *caption_args, str(path)])

    assert result.exit_code == 0, result.stderr
    run.assert_called_once()
    assert run.call_args.args[0] == [_GH, "pr", "edit", "1234", "--attach", f"{path}{attach_suffix}"]
    # an application GITHUB_TOKEN from .env.local must not replace the developer's own login
    assert run.call_args.kwargs["env"]["GH_TOKEN"] == "personal-token"
    add_props.assert_called_once_with(upload_route="gh_attach")
    publish.assert_not_called()


def test_sibling_file_gh_would_read_instead_is_refused(tmp_path: Path) -> None:
    # gh takes the longest existing name before a `#`, so this sibling would be published
    # in place of the validated file.
    path = tmp_path / "after.png"
    path.write_bytes(b"fake bytes")
    secret = tmp_path / "secret.env"
    secret.write_bytes(b"SECRET=1")
    (tmp_path / "after.png#state.png").symlink_to(secret)
    with (
        patch.object(pr_upload, "_gh_with_attach", return_value=_GH),
        patch.object(pr_upload.subprocess, "run") as run,
    ):
        result = CliRunner(mix_stderr=False).invoke(
            upload_image.upload_image, ["--yes", "--pr", "1234", "--alt", "state.png", str(path)]
        )

    assert result.exit_code != 0
    run.assert_not_called()


def test_failed_gh_attach_exits_nonzero(tmp_path: Path) -> None:
    path = tmp_path / "after.png"
    path.write_bytes(b"fake bytes")
    with (
        patch.object(pr_upload, "_gh_with_attach", return_value=_GH),
        patch.object(pr_upload, "github_token", return_value=None),
        patch.object(pr_upload.subprocess, "run", return_value=_gh_returns("", returncode=1)),
        patch.object(pr_assets, "publish") as publish,
    ):
        result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", "--pr", "1234", str(path)])

    assert result.exit_code != 0
    publish.assert_not_called()


@pytest.mark.parametrize(
    ("extra_args", "detected_pr", "gh", "route"),
    [
        (["--print-markdown"], 1234, _GH, "pr_assets_requested"),
        ([], None, _GH, "pr_assets_no_pr"),
        ([], 1234, None, "pr_assets_gh_without_attach"),
    ],
    ids=["print_markdown", "no_pr", "gh_without_attach"],
)
def test_pr_assets_route_records_why_gh_was_skipped(
    tmp_path: Path, extra_args: list[str], detected_pr: int | None, gh: str | None, route: str
) -> None:
    path = tmp_path / "after.png"
    path.write_bytes(b"fake bytes")
    with (
        patch.object(pr_upload, "_open_pull_request", return_value=detected_pr),
        patch.object(pr_upload, "_gh_with_attach", return_value=gh),
        patch.object(pr_upload.subprocess, "run") as run,
        patch.object(pr_upload.telemetry, "add_command_properties") as add_props,
        patch.object(pr_assets, "publish", return_value=["https://example.com/a.png"]) as publish,
    ):
        result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", *extra_args, str(path)])

    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == "![after](https://example.com/a.png)"
    add_props.assert_called_once_with(upload_route=route)
    publish.assert_called_once()
    run.assert_not_called()
