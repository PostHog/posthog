"""Tests for the shared pr-assets client.

Moved here with the plumbing when it was extracted from upload_image: the exact key
shape, the signed git upload, the single retry on a concurrent push race, the
signed-commit guidance, and the validation gates both upload commands share.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from hogli_commands import pr_assets

_KEY_RE = r"\d{4}/\d{2}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_PNG_ONLY = frozenset({"png"})


@pytest.fixture
def png(tmp_path: Path) -> Path:
    path = tmp_path / "diagram.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n fake bytes")
    return path


def _git_result(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", *args], returncode, stdout=stdout, stderr=stderr)


def test_make_key_shape() -> None:
    # YYYY/MM/<uuid4>.<ext>: the README-pinned layout keeps the tree browsable and prunable.
    assert re.fullmatch(_KEY_RE + r"\.png", pr_assets.make_key("png"))


def test_upload_many_creates_signed_commit_and_returns_sha(
    png: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], Path | None]] = []
    checkout = tmp_path / "checkout"

    class StaticTemporaryDirectory:
        def __init__(self, prefix: str) -> None:
            self.prefix = prefix

        def __enter__(self) -> str:
            checkout.mkdir()
            return str(checkout)

        def __exit__(self, *args: object) -> None:
            return None

    def fake_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        calls.append((args, cwd))
        if args[:3] == ["clone", "--depth", "1"]:
            Path(args[-1]).mkdir()
        if args == ["rev-parse", "HEAD"]:
            return _git_result(args, stdout="deadbeef\n")
        return _git_result(args)

    monkeypatch.setattr(pr_assets.tempfile, "TemporaryDirectory", StaticTemporaryDirectory)
    monkeypatch.setattr(pr_assets, "_git", fake_git)

    sha = pr_assets.upload_many([pr_assets.AssetUpload(path=png, key="2026/08/diagram.png")], "add screenshot")

    assert sha == "deadbeef"
    assert (checkout / "pr-assets" / "2026" / "08" / "diagram.png").read_bytes() == png.read_bytes()
    assert (["commit", "-S", "-m", "add screenshot"], checkout / "pr-assets") in calls
    assert (["push", "origin", "HEAD:main"], checkout / "pr-assets") in calls


def test_upload_many_rebases_once_after_push_race(png: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pushes = 0
    calls: list[list[str]] = []

    class StaticTemporaryDirectory:
        def __init__(self, prefix: str) -> None:
            self.prefix = prefix

        def __enter__(self) -> str:
            return str(tmp_path)

        def __exit__(self, *args: object) -> None:
            return None

    def fake_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        nonlocal pushes
        calls.append(args)
        if args[:3] == ["clone", "--depth", "1"]:
            Path(args[-1]).mkdir()
        if args == ["push", "origin", "HEAD:main"]:
            pushes += 1
            if pushes == 1:
                return _git_result(args, returncode=1, stderr="! [rejected] HEAD -> main (fetch first)")
        if args == ["rev-parse", "HEAD"]:
            return _git_result(args, stdout="cafebabe\n")
        return _git_result(args)

    monkeypatch.setattr(pr_assets.tempfile, "TemporaryDirectory", StaticTemporaryDirectory)
    monkeypatch.setattr(pr_assets, "_git", fake_git)

    sha = pr_assets.upload_many([pr_assets.AssetUpload(path=png, key="2026/08/diagram.png")], "add screenshot")

    assert sha == "cafebabe"
    assert pushes == 2
    assert ["pull", "--rebase", "origin", "main"] in calls


def test_upload_many_points_signed_commit_rejections_at_git_signing(
    png: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StaticTemporaryDirectory:
        def __init__(self, prefix: str) -> None:
            self.prefix = prefix

        def __enter__(self) -> str:
            return str(tmp_path)

        def __exit__(self, *args: object) -> None:
            return None

    def fake_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        if args[:3] == ["clone", "--depth", "1"]:
            Path(args[-1]).mkdir()
        if args == ["push", "origin", "HEAD:main"]:
            return _git_result(
                args,
                returncode=1,
                stderr="GH013: Repository rule violations found\nCommits must have verified signatures.",
            )
        return _git_result(args)

    monkeypatch.setattr(pr_assets.tempfile, "TemporaryDirectory", StaticTemporaryDirectory)
    monkeypatch.setattr(pr_assets, "_git", fake_git)

    with pytest.raises(pr_assets.click.ClickException, match="requires verified signed commits"):
        pr_assets.upload_many([pr_assets.AssetUpload(path=png, key="2026/08/diagram.png")], "add screenshot")


def test_git_error_hint_keeps_dns_failures_distinct_from_ssh_auth() -> None:
    hint = pr_assets._hint_for_git_error("ssh: Could not resolve hostname github.com")

    assert "network/DNS" in hint
    assert "SSH key" not in hint


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
