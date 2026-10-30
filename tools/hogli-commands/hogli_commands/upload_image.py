"""hogli pr:upload-image: put screenshots in a PR description.

With an open PR and a gh that supports `--attach`, this runs `gh pr edit --attach`, so
the screenshot lands in GitHub's own attachment storage. Otherwise it commits the file to
the public PostHog/pr-assets repo and prints a commit-pinned markdown image line. Running
through hogli means the usage, including which route ran, is tracked by hogli's built-in
command telemetry.

On the pr-assets route, auth reuses a GitHub token from GH_TOKEN/GITHUB_TOKEN or the gh CLI (`gh auth token`),
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
    gh_alt_text=True,
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
@click.option(
    "--print-markdown",
    is_flag=True,
    help="Upload to PostHog/pr-assets and print markdown, instead of attaching to the PR description.",
)
# Hidden on purpose: the first run without it prints the warning and stops, so the caller
# has to read the warning and re-run with --yes. Undocumented is the whole point of the gate.
@click.option("-y", "--yes", is_flag=True, hidden=True)
def upload_image(files: tuple[Path, ...], alt: str | None, pr: int | None, print_markdown: bool, yes: bool) -> None:
    """Attach screenshot(s) to the PR description, or upload them and print markdown.

    With an open PR and a gh whose `pr edit` has `--attach`, runs `gh pr edit --attach`. A reference to the
    local file already in the description, such as `![after](./after.png)`, is rewritten
    to the upload. Any other screenshot is appended to the description.

    With no PR, an older gh, or --print-markdown, uploads to the public PostHog/pr-assets
    repo and prints one `![alt](url)` line per file to stdout (everything else goes to
    stderr). URLs are pinned to the commit sha, so they keep rendering even if the file
    is later moved or deleted.

    \b
        hogli pr:upload-image screenshot.png
        hogli pr:upload-image --alt "dashboard after fix" result.png
        hogli pr:upload-image before.png after.png
        hogli pr:upload-image --print-markdown screenshot.png

    Uploads are PUBLIC (anyone can fetch the URL) and permanent. Never upload customer
    data, secrets, or internal-only information.
    """
    run(files, alt, yes, _KIND, pr, print_markdown)
