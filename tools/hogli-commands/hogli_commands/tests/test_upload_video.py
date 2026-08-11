"""Tests for hogli pr:upload-video.

The storage contract is pinned in ``test_pr_assets``; these guard what is
video-specific: the extension allowlist, the link-style markdown on stdout (a plain
[label](url), never an image embed, since GitHub renders no player for raw-hosted
video), the "add video" commit message, and the --yes gate.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from unittest.mock import Mock, patch

import click
from click.testing import CliRunner
from hogli_commands import pr_assets, pr_upload, upload_video

_URL = "https://raw.githubusercontent.com/PostHog/pr-assets/deadbeef/2026/07/a91c.mp4"


@pytest.fixture
def mp4(tmp_path: Path) -> Path:
    path = tmp_path / "frontend-qa.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake bytes")
    return path


@pytest.fixture(autouse=True)
def no_detected_pr() -> Iterator[None]:
    # Detection shells out to gh, so without this the suite reads whatever branch it runs
    # on and these tests pass or fail depending on whether that branch has a PR.
    with patch.object(pr_upload, "_open_pull_request", return_value=None):
        yield


@contextmanager
def _publishes(*urls: str) -> Iterator[Mock]:
    with patch.object(pr_assets, "publish", return_value=list(urls)) as publish:
        yield publish


@pytest.mark.parametrize("name", ["reel.gif", "still.png", "notes.txt"], ids=["gif", "png", "txt"])
def test_video_allowlist_rejects_non_video_extensions(tmp_path: Path, name: str) -> None:
    # The video command's allowlist is its contract: mp4/webm only; images belong to
    # pr:upload-image.
    path = tmp_path / name
    path.write_bytes(b"data")
    with pytest.raises(click.ClickException) as excinfo:
        pr_assets.validate(path, upload_video._KIND.allowed_exts, upload_video._KIND.max_mb)
    assert "mp4" in str(excinfo.value) and "webm" in str(excinfo.value)


def test_without_yes_uploads_nothing_and_exits_nonzero(mp4: Path) -> None:
    with _publishes(_URL) as publish:
        result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, [str(mp4)])

    assert result.exit_code == 1
    assert not result.stdout
    publish.assert_not_called()


def test_stdout_is_link_markdown_not_image_embed(mp4: Path) -> None:
    with _publishes(_URL):
        result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, ["--yes", str(mp4)])

    assert result.exit_code == 0
    # a video embed renders as a broken image on GitHub, so the leading "!" must stay off
    assert result.stdout.strip() == f"[frontend-qa]({_URL})"


def test_upload_uses_video_commit_message(mp4: Path) -> None:
    with _publishes(_URL) as publish:
        result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, ["--yes", str(mp4)])

    assert result.exit_code == 0
    assert publish.call_args.kwargs["message"] == "add video"


def test_pr_flag_reaches_the_commit_message(mp4: Path) -> None:
    # Guards the wiring, which each command does for itself: a --pr the command accepts but
    # never forwards would leave the asset untraceable.
    with _publishes(_URL) as publish:
        result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, ["--yes", "--pr", "1234", str(mp4)])

    assert result.exit_code == 0
    assert publish.call_args.kwargs["message"] == "add video for posthog#1234"


@pytest.mark.parametrize("pr", ["0", "-1"], ids=["zero", "negative"])
def test_pr_flag_rejects_numbers_no_pr_can_have(mp4: Path, pr: str) -> None:
    # A typo'd number must fail loudly rather than commit "for posthog#0" to a public repo
    # permanently, and must not quietly take the no-PR fallback either.
    with _publishes(_URL) as publish:
        result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, ["--yes", "--pr", pr, str(mp4)])

    assert result.exit_code != 0
    assert "--pr" in result.stderr
    publish.assert_not_called()


def test_label_rejected_for_multiple_files(mp4: Path, tmp_path: Path) -> None:
    other = tmp_path / "second.webm"
    other.write_bytes(b"webm fake")
    with _publishes(_URL, _URL) as publish:
        result = CliRunner(mix_stderr=False).invoke(
            upload_video.upload_video, ["--yes", "--label", "demo", str(mp4), str(other)]
        )

    assert result.exit_code != 0
    publish.assert_not_called()
