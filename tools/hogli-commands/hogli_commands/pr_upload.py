"""The shared body of pr:upload-image and pr:upload-video.

The two commands differ only in what they accept and how they render what they
published. ``AssetKind`` carries those differences; ``run`` performs the flow they
share: warn, validate, gate on --yes, then publish.

With an open PR and a gh that supports ``--attach``, the files go to GitHub's own
attachment storage through ``gh pr edit --attach``. Otherwise they go to PostHog/pr-assets
and the command prints markdown. The ``upload_route`` command property records which
route ran.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import click
from hogli import telemetry

from hogli_commands import pr_assets

# Short form, matching what people already write by hand in pr-assets. GitHub raises no
# cross-reference event on the target PR for it, so an upload never adds timeline noise.
_SOURCE_REPO: Final = "posthog"


@dataclass(frozen=True, kw_only=True)
class AssetKind:
    """What one upload command accepts, and how it renders the result."""

    noun: str
    caption_flag: str
    allowed_exts: frozenset[str]
    max_mb: int
    commit_message: str
    markdown: str  # formatted with `label` and `url`
    # gh refuses alt text on video, so only kinds that take it get `<file>#<alt>`.
    gh_alt_text: bool


def escape_markdown_label(text: str) -> str:
    """Escape caption text so it cannot truncate the markdown it sits in.

    Backslashes first: a raw backslash before an escaped bracket would read as a
    literal backslash plus an unescaped `]` and close the label early.
    """
    return text.replace("\\", "\\\\").replace("]", "\\]")


def _open_pull_request() -> int | None:
    """The open PR for the current branch, or None when there is not one.

    Uploading before `gh pr create` is normal, so every failure here is silent: a missing
    PR, a missing gh, or a slow network must never block publishing.
    """
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        result = subprocess.run(
            [gh, "pr", "view", "--json", "number", "--jq", ".number"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def _gh_with_attach() -> str | None:
    """The gh binary when its `pr edit` supports `--attach`, or None.

    Every failure falls back to the pr-assets route, so it is silent.
    """
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        result = subprocess.run(
            [gh, "pr", "edit", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return gh if "--attach" in result.stdout else None


def commit_message(kind: AssetKind, pr: int | None) -> str:
    """Name the PR the asset documents, so a stray file can be traced back to it.

    Only the number travels. pr-assets is public and permanent, and a branch name can
    carry a customer or incident name that must not land there.
    """
    if pr is None:
        return kind.commit_message
    return f"{kind.commit_message} for {_SOURCE_REPO}#{pr}"


def _attach_to_pr(gh: str, files: tuple[Path, ...], caption: str | None, kind: AssetKind, pr: int) -> None:
    """Attach every file to the PR description through `gh pr edit --attach`.

    gh rewrites a body reference to the local path, such as `![alt](./shot.png)`, to the
    uploaded asset, and appends a reference for every other file.
    """
    args = [gh, "pr", "edit", str(pr)]
    for path in files:
        label = caption if caption is not None else path.stem
        args += ["--attach", f"{path}#{label}" if kind.gh_alt_text else str(path)]

    if caption is not None and not kind.gh_alt_text:
        click.secho(f"gh takes no caption for a {kind.noun}, so {kind.caption_flag} is ignored.", fg="yellow", err=True)
    click.secho(f"Attaching to the description of PR #{pr} …", fg="cyan", err=True)
    if subprocess.run(args, check=False).returncode != 0:
        # gh writes the files that did upload into the body before it exits non-zero.
        raise click.ClickException(
            "gh pr edit --attach failed, see its output above. Files that uploaded are already in the "
            "PR description, so re-run only the ones that failed."
        )
    click.secho(f"✓ attached {len(files)} {kind.noun}(s) to the PR description", fg="green", err=True)


def run(
    files: tuple[Path, ...],
    caption: str | None,
    yes: bool,
    kind: AssetKind,
    pr: int | None = None,
    print_markdown: bool = False,
) -> None:
    """Attach every file to the PR description, or publish it to pr-assets and print markdown."""
    click.secho(pr_assets.PUBLIC_WARNING, fg="yellow", bold=True, err=True)

    if caption is not None and len(files) > 1:
        raise click.ClickException(
            f"{kind.caption_flag} captions a single {kind.noun}; drop it to caption each file with its stem"
        )

    for path in files:
        pr_assets.validate(path, kind.allowed_exts, kind.max_mb)

    # Deliberate speed bump: make the caller read the warning above and re-run to confirm.
    if not yes:
        click.secho(
            f"\nNothing uploaded. If the {kind.noun} is safe to publish (no customer data, secrets, or "
            "internal info), re-run the same command with --yes to confirm.",
            fg="yellow",
            err=True,
        )
        raise SystemExit(1)

    number = pr if pr is not None else _open_pull_request()
    if print_markdown:
        route = "pr_assets_requested"
    elif number is None:
        route = "pr_assets_no_pr"
    elif (gh := _gh_with_attach()) is None:
        route = "pr_assets_gh_without_attach"
    else:
        telemetry.add_command_properties(upload_route="gh_attach")
        _attach_to_pr(gh, files, caption, kind, number)
        return
    telemetry.add_command_properties(upload_route=route)

    click.secho(f"Uploading to {pr_assets.REPO} …", fg="cyan", err=True)
    urls = pr_assets.publish(files, message=commit_message(kind, number))

    for path, url in zip(files, urls, strict=True):
        label = caption if caption is not None else path.stem
        # stdout carries only the markdown, so callers can pipe it
        click.echo(kind.markdown.format(label=escape_markdown_label(label), url=url))
        click.secho(f"✓ uploaded {path.name}", fg="green", err=True)
