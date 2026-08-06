"""Tests for hogli pr:upload-video.

The storage contract is pinned in ``test_pr_assets``; these guard what is
video-specific: the extension allowlist, the link-style markdown on stdout (a plain
[label](url), never an image embed, since GitHub renders no player for raw-hosted
video), the "add video" commit message, and the --yes gate.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import Mock, patch

import click
from click.testing import CliRunner
from hogli_commands import pr_assets, upload_video

_URL_RE = r"https://raw\.githubusercontent\.com/PostHog/pr-assets/deadbeef/\d{4}/\d{2}/[0-9a-f-]+\.mp4"


@pytest.fixture
def mp4(tmp_path: Path) -> Path:
    path = tmp_path / "frontend-qa.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake bytes")
    return path


def _resp(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(status_code=200, ok=True, json=lambda: payload)


@contextmanager
def _published(oid: str = "deadbeef") -> Iterator[Mock]:
    session = Mock()
    session.post.side_effect = [
        _resp({"data": {"repository": {"defaultBranchRef": {"name": "main", "target": {"oid": "head1"}}}}}),
        _resp({"data": {"createCommitOnBranch": {"commit": {"oid": oid}}}}),
    ]
    with patch.object(pr_assets.requests, "Session", return_value=session):
        yield session


@pytest.mark.parametrize("name", ["reel.gif", "still.png", "notes.txt"], ids=["gif", "png", "txt"])
def test_video_allowlist_rejects_non_video_extensions(tmp_path: Path, name: str) -> None:
    # The video command's allowlist is its contract: mp4/webm only; images belong to
    # pr:upload-image.
    path = tmp_path / name
    path.write_bytes(b"data")
    with pytest.raises(click.ClickException) as excinfo:
        pr_assets.validate(path, upload_video._KIND.allowed_exts, upload_video._KIND.max_mb)
    assert "mp4" in str(excinfo.value) and "webm" in str(excinfo.value)


def test_without_yes_uploads_nothing_and_exits_nonzero(mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "tok")
    with _published() as session:
        result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, [str(mp4)])

    assert result.exit_code == 1
    assert not result.stdout
    session.post.assert_not_called()


def test_stdout_is_link_markdown_not_image_embed(mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "tok")
    with _published():
        result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, ["--yes", str(mp4)])

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    assert re.fullmatch(r"\[frontend-qa\]\(" + _URL_RE + r"\)", lines[0])
    assert not lines[0].startswith("!")  # a video embed renders as a broken image on GitHub


def test_upload_uses_video_commit_message(mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "tok")
    with _published() as session:
        result = CliRunner(mix_stderr=False).invoke(upload_video.upload_video, ["--yes", str(mp4)])

    assert result.exit_code == 0
    headline = session.post.call_args.kwargs["json"]["variables"]["input"]["message"]["headline"]
    assert headline == "add video"


def test_label_rejected_for_multiple_files(mp4: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate the network so a guard regression fails loudly here instead of committing to
    # the public repo from a token-bearing machine.
    other = tmp_path / "second.webm"
    other.write_bytes(b"webm fake")
    monkeypatch.setenv("GH_TOKEN", "tok")
    with _published() as session:
        result = CliRunner(mix_stderr=False).invoke(
            upload_video.upload_video, ["--yes", "--label", "demo", str(mp4), str(other)]
        )
    assert result.exit_code != 0
    session.post.assert_not_called()
