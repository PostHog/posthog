"""Tests for hogli pr:upload-image.

The framework's parametrized ``--help`` test covers command wellformedness, and the
storage contract (single commit, pinned URLs, retries, validation gates) is pinned in
``test_pr_assets``. These guard what is command-specific: the image markdown that lands
on stdout and nothing else, the --alt contract, the extension allowlist, and the --yes
confirmation gate.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from unittest.mock import Mock, patch

import click
from click.testing import CliRunner
from hogli_commands import pr_assets, pr_upload, upload_image

_URL = "https://raw.githubusercontent.com/PostHog/pr-assets/abc123/2026/07/f7c1.png"


@pytest.fixture
def png(tmp_path: Path) -> Path:
    path = tmp_path / "diagram.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n fake bytes")
    return path


@pytest.fixture(autouse=True)
def no_detected_pr() -> Iterator[None]:
    # Detection shells out to gh, so without this the suite reads whatever branch it runs
    # on and these tests pass or fail depending on whether that branch has a PR.
    with patch.object(pr_upload, "_open_pull_request", return_value=None):
        yield


@contextmanager
def _publishes(*urls: str) -> Iterator[Mock]:
    """Stand in for storage so these tests turn on the command, not the GitHub wire format."""
    with patch.object(pr_assets, "publish", return_value=list(urls)) as publish:
        yield publish


def test_command_prints_only_markdown_to_stdout(png: Path) -> None:
    with _publishes(_URL):
        result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", str(png)])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"![diagram]({_URL})"
    # the public-repo warning must reach stderr, never stdout (stdout is piped into PRs verbatim)
    assert "PUBLIC" in result.stderr
    assert "PUBLIC" not in result.stdout


@pytest.mark.parametrize(
    ("alt", "expected_label"),
    [
        ("before / after", "before / after"),
        ("", ""),
        ("chart]v2", "chart\\]v2"),
        ("chart\\]v2", "chart\\\\\\]v2"),
    ],
    ids=["override", "empty_honored", "bracket_escaped", "backslash_escaped"],
)
def test_command_caption_rendering(png: Path, alt: str, expected_label: str) -> None:
    # --alt is used verbatim (empty stays empty, not replaced by the stem) and its markdown
    # metacharacters are escaped so a `]` can't truncate the embed.
    with _publishes(_URL):
        result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", "--alt", alt, str(png)])

    assert result.stdout.strip() == f"![{expected_label}]({_URL})"


def test_pr_flag_reaches_the_commit_message(png: Path) -> None:
    # Guards the wiring, which each command does for itself: a --pr the command accepts but
    # never forwards would leave the asset untraceable.
    with _publishes(_URL) as publish:
        result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", "--pr", "1234", str(png)])

    assert result.exit_code == 0
    assert publish.call_args.kwargs["message"] == "add screenshot for posthog#1234"


@pytest.mark.parametrize("pr", ["0", "-1"], ids=["zero", "negative"])
def test_pr_flag_rejects_numbers_no_pr_can_have(png: Path, pr: str) -> None:
    # A typo'd number must fail loudly rather than commit "for posthog#0" to a public repo
    # permanently, and must not quietly take the no-PR fallback either.
    with _publishes(_URL) as publish:
        result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", "--pr", pr, str(png)])

    assert result.exit_code != 0
    assert "--pr" in result.stderr
    publish.assert_not_called()


def test_requires_yes_before_uploading(png: Path) -> None:
    # The gate: a first run without --yes must warn and abort without uploading, so the
    # caller has to read the warning and re-run to confirm the public upload.
    with _publishes(_URL) as publish:
        result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, [str(png)])

    assert result.exit_code != 0
    assert "--yes" in result.stderr
    assert not result.stdout  # no markdown emitted
    publish.assert_not_called()


def test_rejects_alt_with_multiple_files(tmp_path: Path) -> None:
    # A single --alt can't caption N files distinctly; reject it rather than silently
    # captioning every image identically.
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    with _publishes(_URL, _URL) as publish:
        result = CliRunner(mix_stderr=False).invoke(
            upload_image.upload_image, ["--yes", "--alt", "shared", str(a), str(b)]
        )

    assert result.exit_code != 0
    assert "--alt" in result.stderr
    publish.assert_not_called()


@pytest.mark.parametrize("name", ["notes.txt", "clip.mp4", "diagram.svg"], ids=["txt", "mp4", "svg"])
def test_image_allowlist_rejects_non_image_extensions(tmp_path: Path, name: str) -> None:
    # The image command's allowlist is its contract: no videos, and no svg (served as
    # text/plain, so GitHub won't inline it).
    path = tmp_path / name
    path.write_bytes(b"data")
    with pytest.raises(click.ClickException, match="unsupported"):
        pr_assets.validate(path, upload_image._KIND.allowed_exts, upload_image._KIND.max_mb)


def test_symlink_is_rejected_without_any_upload(tmp_path: Path) -> None:
    target = tmp_path / "secret.env"
    target.write_bytes(b"SECRET=1")
    link = tmp_path / "screenshot.png"
    link.symlink_to(target)
    with _publishes(_URL) as publish:
        result = CliRunner(mix_stderr=False).invoke(upload_image.upload_image, ["--yes", str(link)])

    assert result.exit_code != 0
    publish.assert_not_called()
