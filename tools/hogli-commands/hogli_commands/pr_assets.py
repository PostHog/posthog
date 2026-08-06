"""Shared client for the public PostHog/pr-assets evidence repo.

pr:upload-image and pr:upload-video both publish files here through a local
signed git commit; this module owns the storage concerns they share - the repo
constant, the public-and-permanent warning, the object-key scheme, path
validation, and the signed git upload flow. The commands keep what differs
between them: allowed extensions, the markdown they print, and their flags.
"""

from __future__ import annotations

import shutil
import tempfile
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

import click

REPO: Final = "PostHog/pr-assets"
REMOTE: Final = f"git@github.com:{REPO}.git"
DEFAULT_BRANCH: Final = "main"
PUBLIC_WARNING: Final = (
    "⚠  PUBLIC + PERMANENT upload to PostHog/pr-assets.\n"
    "   SHA-pinned URLs keep serving even after the file is deleted, so an upload cannot be taken back.\n"
    "   Never upload customer data, secrets, tokens, or internal-only information."
)


@dataclass(frozen=True)
class AssetUpload:
    path: Path
    key: str


def escape_markdown_label(text: str) -> str:
    """Escape alt or link text so it cannot truncate the markdown embed.

    Backslashes first: a raw backslash before an escaped bracket would read as a
    literal backslash plus an unescaped `]` and close the label early.
    """
    return text.replace("\\", "\\\\").replace("]", "\\]")


def make_key(ext: str) -> str:
    """Object key for an upload: ``YYYY/MM/<uuid4>.<ext>`` in UTC.

    Random names avoid collisions; the date dirs keep the tree browsable and prunable.
    """
    now = datetime.now(UTC)
    return f"{now:%Y/%m}/{uuid4()}.{ext}"


def validate(path: Path, allowed_exts: frozenset[str], max_mb: int) -> str:
    """Return the lowercased extension, or raise on a symlink / unsupported type / oversized file."""
    # Reject symlinks before any stat/read: a `screenshot.png` link pointing at `.env` would
    # otherwise be followed and its target uploaded to the public repo.
    if path.is_symlink():
        raise click.ClickException(f"{path.name}: refusing to upload a symlink (it could point at a sensitive file)")
    ext = path.suffix.lower().lstrip(".")
    if ext not in allowed_exts:
        allowed = ", ".join(sorted(allowed_exts))
        raise click.ClickException(f"{path.name}: unsupported extension '.{ext}' (allowed: {allowed})")
    size = path.stat().st_size
    if size > max_mb * 1024 * 1024:
        raise click.ClickException(f"{path.name}: {size / 1024 / 1024:.1f} MB exceeds the {max_mb} MB limit")
    return ext


def upload_many(uploads: Sequence[AssetUpload], message: str) -> str:
    """Upload files in one signed commit and return that commit's sha."""
    if not uploads:
        raise click.ClickException("no files to upload")

    with tempfile.TemporaryDirectory(prefix="hogli-pr-assets-") as tempdir:
        repo_dir = Path(tempdir) / "pr-assets"
        clone = _git(["clone", "--depth", "1", REMOTE, str(repo_dir)])
        _check_git(clone, f"clone {REPO}")

        for upload in uploads:
            destination = repo_dir.joinpath(*upload.key.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(upload.path, destination)

        keys = [upload.key for upload in uploads]
        add = _git(["add", "--", *keys], cwd=repo_dir)
        _check_git(add, "stage pr-assets upload")

        commit = _git(["commit", "-S", "-m", message], cwd=repo_dir)
        _check_git(commit, "create a signed pr-assets commit")

        _push(repo_dir)

        rev_parse = _git(["rev-parse", "HEAD"], cwd=repo_dir)
        _check_git(rev_parse, "read the pr-assets commit sha")
        return rev_parse.stdout.strip()


def _push(repo_dir: Path) -> None:
    """Push the current HEAD, retrying once if another upload raced us."""
    push = _git(["push", "origin", f"HEAD:{DEFAULT_BRANCH}"], cwd=repo_dir)
    if push.returncode == 0:
        return

    if _is_non_fast_forward(push):
        rebase = _git(["pull", "--rebase", "origin", DEFAULT_BRANCH], cwd=repo_dir)
        _check_git(rebase, "rebase on the latest pr-assets commit")
        push = _git(["push", "origin", f"HEAD:{DEFAULT_BRANCH}"], cwd=repo_dir)

    _check_git(push, "push the signed pr-assets commit")


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _check_git(result: subprocess.CompletedProcess[str], action: str) -> None:
    if result.returncode == 0:
        return

    output = _git_output(result)
    hint = _hint_for_git_error(output)
    message = f"could not {action}"
    if hint:
        message = f"{message}. {hint}"
    if output:
        message = f"{message}\n\nGit said:\n{output}"
    raise click.ClickException(message)


def _git_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())


def _hint_for_git_error(output: str) -> str:
    lower = output.lower()
    if "verified signatures" in lower or "gpg failed to sign" in lower or "signing failed" in lower:
        return f"{REPO} requires verified signed commits; make sure `git commit -S` works in a normal terminal."
    if "could not resolve hostname" in lower or "temporary failure in name resolution" in lower:
        return "could not resolve GitHub; check network/DNS access and retry."
    if "permission denied (publickey)" in lower or "could not read from remote repository" in lower:
        return f"make sure your GitHub SSH key can write to {REPO}."
    return ""


def _is_non_fast_forward(result: subprocess.CompletedProcess[str]) -> bool:
    output = _git_output(result).lower()
    return (
        "non-fast-forward" in output
        or "fetch first" in output
        or "remote contains work that you do not have locally" in output
    )
