"""Tests for hogli pr:upload-video.

The image command's tests cover the shared upload plumbing (key shape, base64 body,
409 retry); these guard what is video-specific: the extension allowlist, the link-style
markdown on stdout (a plain [label](url), never an image embed, since GitHub renders no
player for raw-hosted video), the "add video" commit message, and the --yes gate.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import Mock, patch

from click.testing import CliRunner
from hogli_commands import upload_video

_URL_RE = r"https://raw\.githubusercontent\.com/PostHog/pr-assets/[0-9a-f]+/\d{4}/\d{2}/[0-9a-f-]+\.mp4"


@pytest.fixture
def mp4(tmp_path: Path) -> Path:
    path = tmp_path / "frontend-qa.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake bytes")
    return path


def _resp(status: int, sha: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status,
        ok=status < 400,
        json=lambda: {"commit": {"sha": sha}} if sha is not None else {},
    )


def test_validate_rejects_non_video_extension(tmp_path: Path) -> None:
    path = tmp_path / "reel.gif"
    path.write_bytes(b"GIF89a")
    with pytest.raises(Exception) as excinfo:
        upload_video._validate(path)
    assert "mp4" in str(excinfo.value) and "webm" in str(excinfo.value)


def test_validate_rejects_symlink(tmp_path: Path, mp4: Path) -> None:
    link = tmp_path / "innocent.mp4"
    link.symlink_to(mp4)
    with pytest.raises(Exception, match="symlink"):
        upload_video._validate(link)


def test_validate_rejects_oversized_file(tmp_path: Path) -> None:
    path = tmp_path / "long.webm"
    path.write_bytes(b"\x00" * (upload_video._MAX_BYTES + 1))
    with pytest.raises(Exception, match="exceeds"):
        upload_video._validate(path)


def test_without_yes_uploads_nothing_and_exits_nonzero(mp4: Path) -> None:
    with patch.object(upload_video, "_upload") as mock_upload:
        result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, [str(mp4)])
    assert result.exit_code == 1
    mock_upload.assert_not_called()


def test_stdout_is_link_markdown_not_image_embed(mp4: Path) -> None:
    session = Mock()
    session.put.return_value = _resp(201, "deadbeef")
    with (
        patch.object(upload_video, "github_token", return_value="tok"),
        patch("requests.Session", return_value=session),
    ):
        result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, ["--yes", str(mp4)])

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    assert re.fullmatch(r"\[frontend-qa\]\(" + _URL_RE.replace("[0-9a-f]+", "deadbeef") + r"\)", lines[0])
    assert not lines[0].startswith("!")


def test_upload_uses_video_commit_message(mp4: Path) -> None:
    session = Mock()
    session.put.return_value = _resp(201, "deadbeef")
    with (
        patch.object(upload_video, "github_token", return_value="tok"),
        patch("requests.Session", return_value=session),
    ):
        result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, ["--yes", str(mp4)])

    assert result.exit_code == 0
    assert session.put.call_args.kwargs["json"]["message"] == "add video"


def test_label_rejected_for_multiple_files(mp4: Path, tmp_path: Path) -> None:
    other = tmp_path / "second.webm"
    other.write_bytes(b"webm fake")
    result = CliRunner(mix_stderr=False).invoke(
        upload_video.upload_video, ["--yes", "--label", "demo", str(mp4), str(other)]
    )
    assert result.exit_code != 0
