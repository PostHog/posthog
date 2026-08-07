"""The shared body of pr:upload-image and pr:upload-video.

The two commands differ only in what they accept and how they render what they
published. ``AssetKind`` carries those differences; ``run`` performs the flow they
share: warn, validate, gate on --yes, publish, print markdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import click

from hogli_commands import pr_assets


@dataclass(frozen=True, kw_only=True)
class AssetKind:
    """What one upload command accepts, and how it renders the result."""

    noun: str
    caption_flag: str
    allowed_exts: frozenset[str]
    max_mb: int
    commit_message: str
    markdown: str  # formatted with `label` and `url`


def escape_markdown_label(text: str) -> str:
    """Escape caption text so it cannot truncate the markdown it sits in.

    Backslashes first: a raw backslash before an escaped bracket would read as a
    literal backslash plus an unescaped `]` and close the label early.
    """
    return text.replace("\\", "\\\\").replace("]", "\\]")


def run(files: tuple[Path, ...], caption: str | None, yes: bool, kind: AssetKind) -> None:
    """Publish every file and print one markdown line each to stdout."""
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

    click.secho(f"Uploading to {pr_assets.REPO} …", fg="cyan", err=True)
    urls = pr_assets.publish(files, message=kind.commit_message)

    for path, url in zip(files, urls, strict=True):
        label = caption if caption is not None else path.stem
        # stdout carries only the markdown, so callers can pipe it
        click.echo(kind.markdown.format(label=escape_markdown_label(label), url=url))
        click.secho(f"✓ uploaded {path.name}", fg="green", err=True)
