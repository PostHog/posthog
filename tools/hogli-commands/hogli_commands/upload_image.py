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

import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

import click
import requests

from hogli_commands.github_auth import github_headers, github_token

_REPO: Final = "PostHog/pr-assets"
# svg is excluded: raw.githubusercontent.com serves it as text/plain, so GitHub won't inline it
_ALLOWED_EXTS: Final = frozenset({"png", "jpg", "jpeg", "gif", "webp"})
_MAX_MB: Final = 10  # GitHub caps image/gif attachments at 10 MB; larger is a video or wrong file
_MAX_BYTES: Final = _MAX_MB * 1024 * 1024
_COMMIT_MESSAGE: Final = "add screenshot"
_PUBLIC_WARNING: Final = (
    "⚠  PUBLIC + PERMANENT upload to PostHog/pr-assets.\n"
    "   SHA-pinned URLs keep serving even after the file is deleted, so an upload cannot be taken back.\n"
    "   Never upload customer data, secrets, tokens, or internal-only information."
)


def _make_key(ext: str) -> str:
    """Object key for an upload: ``YYYY/MM/<uuid4>.<ext>`` in UTC.

    Random names avoid collisions; the date dirs keep the tree browsable and prunable.
    """
    now = datetime.now(UTC)
    return f"{now:%Y/%m}/{uuid4()}.{ext}"


def _encode_base64(path: Path) -> str:
    """Base64-encode the file as a single newline-free line.

    The contents API wants raw base64 with no line breaks; ``b64encode`` (unlike
    ``encodebytes``) never inserts them.
    """
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _put(session: requests.Session, url: str, token: str, body: dict[str, str]) -> requests.Response:
    """PUT to the contents API, turning a network error into a friendly ClickException."""
    try:
        return session.put(url, headers=github_headers(token), json=body, timeout=120)
    except requests.RequestException as exc:
        raise click.ClickException(f"GitHub request failed: {exc}")


def _upload(path: Path, key: str, token: str, session: requests.Session) -> str:
    """PUT the file to the contents API, returning the created commit sha.

    Retries once on HTTP 409 with the same key, since concurrent commits to the repo's
    default branch can race.
    """
    url = f"https://api.github.com/repos/{_REPO}/contents/{key}"
    body = {"message": _COMMIT_MESSAGE, "content": _encode_base64(path)}

    resp = _put(session, url, token, body)
    if resp.status_code == 409:
        # a concurrent commit to the default branch raced us; retry once with the same key
        resp = _put(session, url, token, body)

    if resp.status_code in (403, 404):
        raise click.ClickException(_denied_message(path))
    if not resp.ok:
        raise click.ClickException(f"upload of {path.name} failed (HTTP {resp.status_code})")
    try:
        return resp.json()["commit"]["sha"]
    except (ValueError, KeyError, TypeError) as exc:
        raise click.ClickException(f"GitHub returned an unexpected response uploading {path.name}: {exc}")


def _denied_message(path: Path) -> str:
    """Explain a 403/404: the token can't write to pr-assets (not an org member, or missing scope)."""
    return (
        f"upload of {path.name} was denied. Writing to {_REPO} needs write access to a public PostHog repo: "
        "confirm your token is a PostHog org account with the `repo` scope "
        "(gh users: `gh auth refresh -s repo`; or set GH_TOKEN to a PAT with the repo scope)."
    )


def _validate(path: Path) -> str:
    """Return the lowercased extension, or raise on a symlink / unsupported type / oversized file."""
    # Reject symlinks before any stat/read: a `screenshot.png` link pointing at `.env` would
    # otherwise be followed and its target uploaded to the public repo.
    if path.is_symlink():
        raise click.ClickException(f"{path.name}: refusing to upload a symlink (it could point at a sensitive file)")
    ext = path.suffix.lower().lstrip(".")
    if ext not in _ALLOWED_EXTS:
        allowed = ", ".join(sorted(_ALLOWED_EXTS))
        raise click.ClickException(f"{path.name}: unsupported extension '.{ext}' (allowed: {allowed})")
    size = path.stat().st_size
    if size > _MAX_BYTES:
        raise click.ClickException(f"{path.name}: {size / 1024 / 1024:.1f} MB exceeds the {_MAX_MB} MB limit")
    return ext


def _escape_alt(text: str) -> str:
    """Escape the one markdown metacharacter that would truncate image alt text."""
    return text.replace("]", "\\]")


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
    click.secho(_PUBLIC_WARNING, fg="yellow", bold=True, err=True)

    if alt is not None and len(files) > 1:
        raise click.ClickException("--alt captions a single image; drop it to caption each file with its stem")

    validated = [(path, _validate(path)) for path in files]

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
        key = _make_key(ext)
        click.secho(f"Uploading {path.name} → {_REPO}/{key} …", fg="cyan", err=True)
        sha = _upload(path, key, token, session)
        caption = alt if alt is not None else path.stem
        markdown = f"![{_escape_alt(caption)}](https://raw.githubusercontent.com/{_REPO}/{sha}/{key})"
        click.echo(markdown)  # stdout carries only the markdown, so callers can pipe it
        click.secho(f"✓ uploaded {path.name}", fg="green", err=True)
