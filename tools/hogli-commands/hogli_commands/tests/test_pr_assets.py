"""Tests for the shared pr-assets client.

Moved here with the plumbing when it was extracted from upload_image: the exact key
shape, the base64 content body, the single retry on a concurrent-commit 409, the
denied-PUT guidance, and the validation gates both upload commands share.
"""

from __future__ import annotations

import re
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import Mock

from hogli_commands import pr_assets

_KEY_RE = r"\d{4}/\d{2}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_PNG_ONLY = frozenset({"png"})


@pytest.fixture
def png(tmp_path: Path) -> Path:
    path = tmp_path / "diagram.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n fake bytes")
    return path


def _resp(status: int, sha: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status,
        ok=status < 400,
        json=lambda: {"commit": {"sha": sha}} if sha is not None else {},
    )


def _session(*responses: SimpleNamespace) -> Mock:
    session = Mock()
    session.put.side_effect = responses
    return session


def test_make_key_shape() -> None:
    # YYYY/MM/<uuid4>.<ext>: the README-pinned layout keeps the tree browsable and prunable.
    assert re.fullmatch(_KEY_RE + r"\.png", pr_assets.make_key("png"))


def test_upload_puts_base64_body_and_returns_sha(png: Path) -> None:
    session = _session(_resp(201, "deadbeef"))
    sha = pr_assets.upload(png, "2026/07/abc.png", "tok", session, message="add screenshot")

    assert sha == "deadbeef"
    url = session.put.call_args.args[0]
    assert url == "https://api.github.com/repos/PostHog/pr-assets/contents/2026/07/abc.png"
    body = session.put.call_args.kwargs["json"]
    assert body["message"] == "add screenshot"
    assert body["content"] == base64.b64encode(png.read_bytes()).decode()
    assert "\n" not in body["content"]  # the contents API rejects line-wrapped base64
    assert session.put.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"


def test_upload_retries_once_on_409_with_same_key(png: Path) -> None:
    session = _session(_resp(409), _resp(201, "sha2"))
    sha = pr_assets.upload(png, "2026/07/abc.png", "tok", session, message="add screenshot")

    assert sha == "sha2"
    assert session.put.call_count == 2
    # both attempts target the identical key; a fresh key on retry would orphan the first
    urls = {call.args[0] for call in session.put.call_args_list}
    assert urls == {"https://api.github.com/repos/PostHog/pr-assets/contents/2026/07/abc.png"}


def test_upload_gives_up_after_second_409(png: Path) -> None:
    session = _session(_resp(409), _resp(409))
    with pytest.raises(pr_assets.click.ClickException):
        pr_assets.upload(png, "2026/07/x.png", "tok", session, message="add screenshot")
    assert session.put.call_count == 2  # one retry, then surface the failure


@pytest.mark.parametrize("status", [403, 404], ids=["forbidden", "not_found"])
def test_permission_denied_points_at_org_access(png: Path, status: int) -> None:
    # A denied PUT must explain the write-access fix, not surface a raw error; this is the
    # "only PostHog org members can write" boundary.
    session = _session(_resp(status))
    with pytest.raises(pr_assets.click.ClickException, match="PostHog org"):
        pr_assets.upload(png, "2026/07/x.png", "tok", session, message="add screenshot")


def test_upload_wraps_unexpected_response(png: Path) -> None:
    # A 2xx whose body isn't the contents-API shape must surface as a ClickException, not a
    # raw KeyError traceback.
    session = _session(_resp(201))  # json() -> {} with no commit.sha
    with pytest.raises(pr_assets.click.ClickException, match="unexpected response"):
        pr_assets.upload(png, "2026/07/x.png", "tok", session, message="add screenshot")


def test_validate_rejects_symlink_before_reading_target(tmp_path: Path) -> None:
    # A `screenshot.png` symlink pointing at a sensitive file must be refused before its
    # target is stat'd or read; the .png name would otherwise pass the ext gate and upload .env.
    target = tmp_path / "secret.env"
    target.write_bytes(b"SECRET=1")
    link = tmp_path / "screenshot.png"
    link.symlink_to(target)
    with pytest.raises(pr_assets.click.ClickException, match="symlink"):
        pr_assets.validate(link, _PNG_ONLY, 10)


def test_validate_rejects_extension_outside_allowlist(tmp_path: Path) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"data")
    with pytest.raises(pr_assets.click.ClickException, match="unsupported"):
        pr_assets.validate(path, _PNG_ONLY, 10)


def test_validate_rejects_oversized_file(tmp_path: Path, png: Path) -> None:
    big = tmp_path / "big.png"
    big.write_bytes(b"\x00" * (1024 * 1024 + 1))
    with pytest.raises(pr_assets.click.ClickException, match="exceeds the 1 MB limit"):
        pr_assets.validate(big, _PNG_ONLY, 1)
    assert pr_assets.validate(png, _PNG_ONLY, 1) == "png"
