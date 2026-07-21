"""hogli pr:upload-video: upload short demo videos to the public PostHog/pr-assets repo.

Same storage, auth, and confirmation gate as pr:upload-image (the shared pr_assets
client), but for video files. GitHub renders no inline player for raw-hosted video, so
the printed markdown is a plain [label](url) link that opens or downloads the file
rather than an embed. For an inline player, drag the video into the PR comment editor
by hand instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import click
import requests

from hogli_commands import pr_assets
from hogli_commands.github_auth import github_token

_ALLOWED_EXTS: Final = frozenset({"mp4", "webm"})
# GitHub's own inline-upload cap for videos on free plans, and roomy for the intended
# use: a 10-30 s screen recording of the app at 1280px wide (H.264, CRF 26) comes out
# around 250-650 KB, so 10 MB fits several minutes of UI screencast.
_MAX_MB: Final = 10
_COMMIT_MESSAGE: Final = "add video"


@click.command(name="pr:upload-video")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--label", help="Link text for the markdown (defaults to each file's stem).")
# Hidden on purpose, matching pr:upload-image: the first run without it prints the
# warning and stops, so the caller has to read the warning and re-run with --yes.
@click.option("-y", "--yes", is_flag=True, hidden=True)
def upload_video(files: tuple[Path, ...], label: str | None, yes: bool) -> None:
    """Upload demo video(s) to the public PostHog/pr-assets repo and print link markdown.

    Prints one `[label](url)` line per file to stdout (everything else goes to stderr).
    GitHub does not render an inline player for raw-hosted video, so the link opens or
    downloads the file; for an inline player, drag the video into the PR comment editor
    by hand instead.

    \b
        hogli pr:upload-video demo.mp4
        hogli pr:upload-video --label "duplicate-question demo" frontend-qa.mp4

    Uploads land in a PUBLIC repo (anyone can fetch the URL) and are permanent:
    SHA-pinned URLs keep serving even after the file is deleted. Never upload customer
    data, secrets, or internal-only information.
    """
    click.secho(pr_assets.PUBLIC_WARNING, fg="yellow", bold=True, err=True)

    if label is not None and len(files) > 1:
        raise click.ClickException("--label captions a single video; drop it to label each file with its stem")

    validated = [(path, pr_assets.validate(path, _ALLOWED_EXTS, _MAX_MB)) for path in files]

    if not yes:
        click.secho(
            "\nNothing uploaded. If the video is safe to publish (no customer data, secrets, or internal "
            "info), re-run the same command with --yes to confirm.",
            fg="yellow",
            err=True,
        )
        raise SystemExit(1)

    token = github_token()
    if token is None:
        raise click.ClickException(
            "no GitHub token found. Set GH_TOKEN or GITHUB_TOKEN, or install gh "
            "(https://cli.github.com/) and run `gh auth login`."
        )
    session = requests.Session()

    for path, ext in validated:
        key = pr_assets.make_key(ext)
        click.secho(f"Uploading {path.name} → {pr_assets.REPO}/{key} …", fg="cyan", err=True)
        sha = pr_assets.upload(path, key, token, session, message=_COMMIT_MESSAGE)
        text = label if label is not None else path.stem
        markdown = (
            f"[{pr_assets.escape_markdown_label(text)}](https://raw.githubusercontent.com/{pr_assets.REPO}/{sha}/{key})"
        )
        click.echo(markdown)  # stdout carries only the markdown, so callers can pipe it
        click.secho(f"✓ uploaded {path.name}", fg="green", err=True)
