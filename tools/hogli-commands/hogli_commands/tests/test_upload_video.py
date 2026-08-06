"""Tests for hogli pr:upload-video.

The shared upload plumbing (key shape, signed git upload, validation gates) is pinned
in ``test_pr_assets``; these guard what is video-specific: the extension
allowlist, the link-style markdown on stdout (a plain [label](url), never an image
embed, since GitHub renders no player for raw-hosted video), the "add video" commit
message, and the --yes gate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from unittest.mock import Mock

from click.testing import CliRunner
from hogli_commands import pr_assets, upload_video

_URL_RE = r"https://raw\.githubusercontent\.com/PostHog/pr-assets/deadbeef/\d{4}/\d{2}/[0-9a-f-]+\.mp4"


@pytest.fixture
def mp4(tmp_path: Path) -> Path:
    path = tmp_path / "frontend-qa.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake bytes")
    return path


@pytest.mark.parametrize("name", ["reel.gif", "still.png", "notes.txt"], ids=["gif", "png", "txt"])
def test_video_allowlist_rejects_non_video_extensions(tmp_path: Path, name: str) -> None:
    # The video command's allowlist is its contract: mp4/webm only; images belong to
    # pr:upload-image.
    path = tmp_path / name
    path.write_bytes(b"data")
    with pytest.raises(pr_assets.click.ClickException) as excinfo:
        pr_assets.validate(path, upload_video._ALLOWED_EXTS, upload_video._MAX_MB)
    assert "mp4" in str(excinfo.value) and "webm" in str(excinfo.value)


def test_without_yes_uploads_nothing_and_exits_nonzero(mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload_many = Mock(return_value="x")
    monkeypatch.setattr(pr_assets, "upload_many", upload_many)

    result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, [str(mp4)])

    assert result.exit_code == 1
    assert not result.stdout
    upload_many.assert_not_called()


def test_stdout_is_link_markdown_not_image_embed(mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pr_assets, "upload_many", Mock(return_value="deadbeef"))

    result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, ["--yes", str(mp4)])

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    assert re.fullmatch(r"\[frontend-qa\]\(" + _URL_RE + r"\)", lines[0])
    assert not lines[0].startswith("!")  # a video embed renders as a broken image on GitHub


def test_upload_uses_video_commit_message(mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload_many = Mock(return_value="deadbeef")
    monkeypatch.setattr(pr_assets, "upload_many", upload_many)

    result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, ["--yes", str(mp4)])

    assert result.exit_code == 0
    assert upload_many.call_args.kwargs["message"] == "add video"


def test_label_rejected_for_multiple_files(mp4: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate the network so a guard regression fails loudly here instead of PUTting to
    # the public repo from a token-bearing machine.
    other = tmp_path / "second.webm"
    other.write_bytes(b"webm fake")
    upload_many = Mock(return_value="x")
    monkeypatch.setattr(pr_assets, "upload_many", upload_many)

    result = CliRunner(mix_stderr=False).invoke(
        upload_video.upload_video, ["--yes", "--label", "demo", str(mp4), str(other)]
    )
    assert result.exit_code != 0
    upload_many.assert_not_called()
