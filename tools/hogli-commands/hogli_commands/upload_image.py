"""hogli pr:upload-image: upload screenshots to the public PostHog/pr-assets repo.

Turns a local screenshot into an embeddable, commit-pinned markdown image line for a PR
description in one command. Running through hogli means the usage is tracked by hogli's
built-in command telemetry.

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

from hogli_commands.pr_upload import AssetKind, run

_KIND: Final = AssetKind(
    noun="image",
    caption_flag="--alt",
    # svg is excluded: raw.githubusercontent.com serves it as text/plain, so GitHub won't inline it
    allowed_exts=frozenset({"png", "jpg", "jpeg", "gif", "webp"}),
    max_mb=10,  # GitHub caps image/gif attachments at 10 MB; larger is a video or wrong file
    commit_message="add screenshot",
    markdown="![{label}]({url})",
)


@click.command(name="pr:upload-image")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--alt", help="Alt text for the markdown (defaults to each file's stem).")
# IntRange rather than int: a typo'd 0 or -1 would otherwise commit "for posthog#0" to a
# public repo permanently, and the plain-message fallback would hide the typo instead of
# reporting it.
@click.option(
    "--pr",
    type=click.IntRange(min=1),
    help="PR the screenshot documents (defaults to the current branch's open PR).",
)
# Hidden on purpose: the first run without it prints the warning and stops, so the caller
# has to read the warning and re-run with --yes. Undocumented is the whole point of the gate.
@click.option("-y", "--yes", is_flag=True, hidden=True)
def upload_image(files: tuple[Path, ...], alt: str | None, pr: int | None, yes: bool) -> None:
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
    run(files, alt, yes, _KIND, pr)
