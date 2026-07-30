"""hogli pr:upload-image: upload screenshots to the public PostHog/pr-assets repo.

Wraps the GitHub contents API upload documented in the pr-assets README so engineers
and agents can turn a local screenshot into an embeddable, SHA-pinned markdown image
line for a PR description with one command. Running through hogli means the usage is
tracked by hogli's built-in command telemetry.

Auth reuses a GitHub token from GH_TOKEN/GITHUB_TOKEN or the gh CLI (`gh auth token`),
so it works with or without gh installed as long as a token with write access to a
PostHog org repo is available. The target repo is public by design: GitHub renders PR
images through its anonymous camo proxy, which requires anonymous read. The command
warns about this on every run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import click
import requests

from hogli_commands import pr_assets
from hogli_commands.github_auth import github_token

# svg is excluded: raw.githubusercontent.com serves it as text/plain, so GitHub won't inline it
_ALLOWED_EXTS: Final = frozenset({"png", "jpg", "jpeg", "gif", "webp"})
_MAX_MB: Final = 10  # GitHub caps image/gif attachments at 10 MB; larger is a video or wrong file
_COMMIT_MESSAGE: Final = "add screenshot"


@click.command(name="pr:upload-image")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--alt", help="Alt text for the markdown (defaults to each file's stem).")
# Hidden on purpose: the first run without it prints the warning and stops, so the caller
# has to read the warning and re-run with --yes. Undocumented is the whole point of the gate.
@click.option("-y", "--yes", is_flag=True, hidden=True)
def upload_image(files: tuple[Path, ...], alt: str | None, yes: bool) -> None:
    """Upload screenshot(s) to the public PostHog/pr-assets repo and print embeddable markdown.

    Prints one `![alt](url)` line per file to stdout (everything else goes to stderr),
    so you can pipe or copy the markdown straight into a PR description. URLs are pinned
    to the commit sha, so they keep rendering even if the file is later moved or deleted.

    \b
        hogli pr:upload-image screenshot.png
        hogli pr:upload-image --alt "dashboard after fix" result.png
        hogli pr:upload-image before.png after.png

    Uploads land in a PUBLIC repo (GitHub image embeds require anonymous read) and are
    permanent: SHA-pinned URLs keep serving even after the file is deleted. Never upload
    customer data, secrets, or internal-only information.
    """
    click.secho(pr_assets.PUBLIC_WARNING, fg="yellow", bold=True, err=True)

    if alt is not None and len(files) > 1:
        raise click.ClickException("--alt captions a single image; drop it to caption each file with its stem")

    validated = [(path, pr_assets.validate(path, _ALLOWED_EXTS, _MAX_MB)) for path in files]

    # Deliberate speed bump: make the caller read the warning above and re-run to confirm.
    if not yes:
        click.secho(
            "\nNothing uploaded. If the image is safe to publish (no customer data, secrets, or internal "
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
        caption = alt if alt is not None else path.stem
        markdown = f"![{pr_assets.escape_markdown_label(caption)}](https://raw.githubusercontent.com/{pr_assets.REPO}/{sha}/{key})"
        click.echo(markdown)  # stdout carries only the markdown, so callers can pipe it
        click.secho(f"✓ uploaded {path.name}", fg="green", err=True)
