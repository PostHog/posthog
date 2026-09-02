"""hogli pr:upload-video: upload short demo videos to the public PostHog/pr-assets repo.

Same storage, auth, and confirmation gate as pr:upload-image (the shared pr_upload
body), but for video files. GitHub renders no inline player for raw-hosted video, so
the printed markdown is a plain [label](url) link that opens or downloads the file
rather than an embed. For an inline player, drag the video into the PR comment editor
by hand instead.
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
)


@click.command(name="pr:upload-video")
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--label", help="Link text for the markdown (defaults to each file's stem).")
# IntRange rather than int, matching pr:upload-image: a typo'd 0 or -1 would otherwise
# commit "for posthog#0" to a public repo permanently.
@click.option(
    "--pr",
    type=click.IntRange(min=1),
    help="PR the video documents (defaults to the current branch's open PR).",
)
# Hidden on purpose, matching pr:upload-image: the first run without it prints the
# warning and stops, so the caller has to read the warning and re-run with --yes.
@click.option("-y", "--yes", is_flag=True, hidden=True)
def upload_video(files: tuple[Path, ...], label: str | None, pr: int | None, yes: bool) -> None:
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
    run(files, label, yes, _KIND, pr)
