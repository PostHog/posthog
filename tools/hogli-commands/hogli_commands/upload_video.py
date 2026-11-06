"""hogli pr:upload-video: put short demo videos in a PR description.

Same routes, auth, and confirmation gate as pr:upload-image (the shared pr_upload body),
but for video files. On the gh route the video renders as an inline player. On the
pr-assets route GitHub renders no player for raw-hosted video, so the printed markdown
is a plain [label](url) link that opens or downloads the file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import click

from hogli_commands.pr_upload import AssetKind, run

_KIND: Final = AssetKind(
    noun="video",
    caption_flag="--label",
    allowed_exts=frozenset({"mp4", "webm"}),
    # GitHub's own inline-upload cap for videos on free plans, and roomy for the intended
    # use: a 10-30 s screen recording of the app at 1280px wide (H.264, CRF 26) comes out
    # around 250-650 KB, so 10 MB fits several minutes of UI screencast.
    max_mb=10,
    commit_message="add video",
    markdown="[{label}]({url})",
    gh_alt_text=False,
)


@click.command(name="pr:upload-video")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--label", help="Link text for the pr-assets markdown (defaults to each file's stem).")
# IntRange rather than int, matching pr:upload-image: a typo'd 0 or -1 would otherwise
# commit "for posthog#0" to a public repo permanently.
@click.option(
    "--pr",
    type=click.IntRange(min=1),
    help="PR the video documents (defaults to the current branch's open PR).",
)
@click.option(
    "--print-markdown",
    is_flag=True,
    help="Upload to PostHog/pr-assets and print a link, instead of attaching to the PR description.",
)
# Hidden on purpose, matching pr:upload-image: the first run without it prints the
# warning and stops, so the caller has to read the warning and re-run with --yes.
@click.option("-y", "--yes", is_flag=True, hidden=True)
def upload_video(files: tuple[Path, ...], label: str | None, pr: int | None, print_markdown: bool, yes: bool) -> None:
    """Attach demo video(s) to the PR description, or upload them and print link markdown.

    With an open PR and a gh whose `pr edit` has `--attach`, runs `gh pr edit --attach`
    and the video renders as an inline player. A reference to the local file already in
    the description is rewritten to the upload. Any other video is appended. A video
    takes no caption on this route, so --label is ignored.

    With no PR, an older gh, or --print-markdown, uploads to the public PostHog/pr-assets
    repo and prints one `[label](url)` line per file to stdout (everything else goes to
    stderr). GitHub renders no player for raw-hosted video, so the link opens or
    downloads the file.

    \b
        hogli pr:upload-video demo.mp4
        hogli pr:upload-video --label "duplicate-question demo" frontend-qa.mp4

    Uploads are PUBLIC (anyone can fetch the URL) and permanent. Never upload customer
    data, secrets, or internal-only information.
    """
    run(files, label, yes, _KIND, pr, print_markdown)
