"""Tests for hogli pr:upload-image.

The framework's parametrized ``--help`` test covers command wellformedness, and the
shared upload plumbing (key shape, signed git upload, validation gates) is pinned
in ``test_pr_assets``. These guard what is command-specific: the SHA-pinned image
markdown that lands on stdout and nothing else, the --alt contract, the extension
allowlist, and the --yes confirmation gate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from unittest.mock import Mock

from click.testing import CliRunner
from hogli_commands import pr_assets, upload_image

_KEY_RE = r"\d{4}/\d{2}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


@pytest.fixture
def png(tmp_path: Path) -> Path:
    path = tmp_path / "diagram.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n fake bytes")
    return path


def test_command_prints_only_sha_pinned_markdown_to_stdout(png: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload_many = Mock(return_value="abc123")
    monkeypatch.setattr(pr_assets, "upload_many", upload_many)

    result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", str(png)])

    assert result.exit_code == 0
    line = result.stdout.strip()
    assert re.fullmatch(
        rf"!\[diagram\]\(https://raw\.githubusercontent\.com/PostHog/pr-assets/abc123/{_KEY_RE}\.png\)", line
    )
    # the public-repo warning must reach stderr, never stdout (stdout is piped into PRs verbatim)
    assert "PUBLIC" in result.stderr
    assert "PUBLIC" not in result.stdout
    upload_many.assert_called_once()


@pytest.mark.parametrize(
    ("alt", "expected_prefix"),
    [
        ("before / after", "![before / after]("),
        ("", "!["),
        ("chart]v2", "![chart\\]v2]("),
        ("chart\\]v2", "![chart\\\\\\]v2]("),
    ],
    ids=["override", "empty_honored", "bracket_escaped", "backslash_escaped"],
)
def test_command_caption_rendering(png: Path, monkeypatch: pytest.MonkeyPatch, alt: str, expected_prefix: str) -> None:
    # --alt is used verbatim (empty stays empty, not replaced by the stem) and its markdown
    # metacharacters are escaped so a `]` can't truncate the embed.
    monkeypatch.setattr(pr_assets, "upload_many", Mock(return_value="abc123"))

    result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", "--alt", alt, str(png)])

    assert result.stdout.strip().startswith(expected_prefix)


def test_requires_yes_before_uploading(png: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The gate: a first run without --yes must warn and abort without uploading, so the
    # caller has to read the warning and re-run to confirm the public upload.
    upload_many = Mock(return_value="x")
    monkeypatch.setattr(pr_assets, "upload_many", upload_many)

    result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, [str(png)])

    assert result.exit_code != 0
    assert "--yes" in result.stderr
    assert not result.stdout  # no markdown emitted
    upload_many.assert_not_called()


def test_rejects_alt_with_multiple_files(tmp_path: Path) -> None:
    # A single --alt can't caption N files distinctly; reject it rather than silently
    # captioning every image identically.
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", "--alt", "shared", str(a), str(b)])

    assert result.exit_code != 0
    assert "--alt" in result.stderr


@pytest.mark.parametrize("name", ["notes.txt", "clip.mp4", "diagram.svg"], ids=["txt", "mp4", "svg"])
def test_image_allowlist_rejects_non_image_extensions(tmp_path: Path, name: str) -> None:
    # The image command's allowlist is its contract: no videos, and no svg (served as
    # text/plain, so GitHub won't inline it).
    path = tmp_path / name
    path.write_bytes(b"data")
    with pytest.raises(pr_assets.click.ClickException, match="unsupported"):
        pr_assets.validate(path, upload_image._ALLOWED_EXTS, upload_image._MAX_MB)


def test_symlink_is_rejected_on_stderr_without_any_upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "secret.env"
    target.write_bytes(b"SECRET=1")
    link = tmp_path / "screenshot.png"
    link.symlink_to(target)
    upload_many = Mock(return_value="x")
    monkeypatch.setattr(pr_assets, "upload_many", upload_many)

    result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", str(link)])

    assert result.exit_code != 0
    upload_many.assert_not_called()
