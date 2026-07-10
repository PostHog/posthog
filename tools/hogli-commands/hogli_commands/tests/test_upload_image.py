"""Tests for hogli pr:upload-image.

The framework's parametrized ``--help`` test covers command wellformedness; these guard
the upload contract the README pins down: the exact key shape, the base64 content body,
the SHA-pinned markdown that lands on stdout and nothing else, the single retry on a
concurrent-commit 409, and the --yes confirmation gate. Token sourcing lives in
``test_github_auth`` since it moved to the shared helper.
"""

from __future__ import annotations

import re
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import Mock, patch

from click.testing import CliRunner
from hogli_commands import github_auth, upload_image

_KEY_RE = r"\d{4}/\d{2}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


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
    assert re.fullmatch(_KEY_RE + r"\.png", upload_image._make_key("png"))


def test_upload_puts_base64_body_and_returns_sha(png: Path) -> None:
    session = _session(_resp(201, "deadbeef"))
    sha = upload_image._upload(png, "2026/07/abc.png", "tok", session)

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
    sha = upload_image._upload(png, "2026/07/abc.png", "tok", session)

    assert sha == "sha2"
    assert session.put.call_count == 2
    # both attempts target the identical key; a fresh key on retry would orphan the first
    urls = {call.args[0] for call in session.put.call_args_list}
    assert urls == {"https://api.github.com/repos/PostHog/pr-assets/contents/2026/07/abc.png"}


def test_upload_gives_up_after_second_409(png: Path) -> None:
    session = _session(_resp(409), _resp(409))
    with pytest.raises(upload_image.click.ClickException):
        upload_image._upload(png, "2026/07/x.png", "tok", session)
    assert session.put.call_count == 2  # one retry, then surface the failure


@pytest.mark.parametrize("status", [403, 404], ids=["forbidden", "not_found"])
def test_permission_denied_points_at_org_access(png: Path, status: int) -> None:
    # A denied PUT must explain the write-access fix, not surface a raw error; this is the
    # "only PostHog org members can write" boundary.
    session = _session(_resp(status))
    with pytest.raises(upload_image.click.ClickException, match="PostHog org"):
        upload_image._upload(png, "2026/07/x.png", "tok", session)


def test_upload_wraps_unexpected_response(png: Path) -> None:
    # A 2xx whose body isn't the contents-API shape must surface as a ClickException, not a
    # raw KeyError traceback.
    session = _session(_resp(201))  # json() -> {} with no commit.sha
    with pytest.raises(upload_image.click.ClickException, match="unexpected response"):
        upload_image._upload(png, "2026/07/x.png", "tok", session)


def test_command_prints_only_sha_pinned_markdown_to_stdout(png: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "tok")  # token via the real env path
    with patch.object(upload_image.requests, "Session", return_value=_session(_resp(201, "abc123"))):
        result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", str(png)])

    assert result.exit_code == 0
    line = result.stdout.strip()
    assert re.fullmatch(
        rf"!\[diagram\]\(https://raw\.githubusercontent\.com/PostHog/pr-assets/abc123/{_KEY_RE}\.png\)", line
    )
    # the public-repo warning must reach stderr, never stdout (stdout is piped into PRs verbatim)
    assert "PUBLIC" in result.stderr
    assert "PUBLIC" not in result.stdout


@pytest.mark.parametrize(
    ("alt", "expected_prefix"),
    [("before / after", "![before / after]("), ("", "!["), ("chart]v2", "![chart\\]v2](")],
    ids=["override", "empty_honored", "bracket_escaped"],
)
def test_command_caption_rendering(png: Path, monkeypatch: pytest.MonkeyPatch, alt: str, expected_prefix: str) -> None:
    # --alt is used verbatim (empty stays empty, not replaced by the stem) and its markdown
    # metacharacters are escaped so a `]` can't truncate the embed.
    monkeypatch.setenv("GH_TOKEN", "tok")
    with patch.object(upload_image.requests, "Session", return_value=_session(_resp(201, "abc123"))):
        result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", "--alt", alt, str(png)])

    assert result.stdout.strip().startswith(expected_prefix)


def test_requires_yes_before_uploading(png: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The gate: a first run without --yes must warn and abort without uploading, so the
    # caller has to read the warning and re-run to confirm the public upload.
    monkeypatch.setenv("GH_TOKEN", "tok")
    session = _session(_resp(201, "x"))
    with patch.object(upload_image.requests, "Session", return_value=session):
        result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, [str(png)])

    assert result.exit_code != 0
    assert "--yes" in result.stderr
    assert not result.stdout  # no markdown emitted
    session.put.assert_not_called()


def test_command_errors_without_a_token(png: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(github_auth.shutil, "which", lambda _: None)  # no env, no gh -> no token
    result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", str(png)])

    assert result.exit_code != 0
    assert "token" in result.stderr.lower()


def test_rejects_alt_with_multiple_files(tmp_path: Path) -> None:
    # A single --alt can't caption N files distinctly; reject it rather than silently
    # captioning every image identically.
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", "--alt", "shared", str(a), str(b)])

    assert result.exit_code != 0
    assert "--alt" in result.stderr


@pytest.mark.parametrize(
    ("name", "expected"),
    [("notes.txt", "unsupported"), ("clip.mp4", "unsupported"), ("diagram.svg", "unsupported")],
    ids=["txt", "mp4", "svg"],
)
def test_rejects_unsupported_extensions(tmp_path: Path, name: str, expected: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"data")
    with pytest.raises(upload_image.click.ClickException, match=expected):
        upload_image._validate(path)


def test_validate_rejects_symlink_before_reading_target(tmp_path: Path) -> None:
    # A `screenshot.png` symlink pointing at a sensitive file must be refused before its
    # target is stat'd or read; the .png name would otherwise pass the ext gate and upload .env.
    target = tmp_path / "secret.env"
    target.write_bytes(b"SECRET=1")
    link = tmp_path / "screenshot.png"
    link.symlink_to(target)
    with pytest.raises(upload_image.click.ClickException, match="symlink"):
        upload_image._validate(link)


def test_symlink_is_rejected_on_stderr_without_any_upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "secret.env"
    target.write_bytes(b"SECRET=1")
    link = tmp_path / "screenshot.png"
    link.symlink_to(target)
    monkeypatch.setenv("GH_TOKEN", "tok")
    session = _session(_resp(201, "x"))
    with patch.object(upload_image.requests, "Session", return_value=session):
        result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", str(link)])

    assert result.exit_code != 0
    assert "symlink" in result.stderr.lower()
    assert not result.stdout  # nothing uploaded, no markdown
    session.put.assert_not_called()  # the target was never fetched or PUT


def test_rejects_oversized_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "huge.png"
    path.write_bytes(b"x")
    monkeypatch.setattr(upload_image, "_MAX_BYTES", 0)
    with pytest.raises(upload_image.click.ClickException, match="exceeds the"):
        upload_image._validate(path)
