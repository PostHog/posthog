"""Shared client for the public PostHog/pr-assets evidence repo.

pr:upload-image and pr:upload-video both publish files here through the GitHub
contents API; this module owns the storage concerns they share - the repo
constant, the public-and-permanent warning, the object-key scheme, path
validation, and the upload PUT with its concurrent-commit retry. The commands
keep what differs between them: allowed extensions, the markdown they print,
and their flags.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

import click
import requests

from hogli_commands.github_auth import github_headers

REPO: Final = "PostHog/pr-assets"
PUBLIC_WARNING: Final = (
    "⚠  PUBLIC + PERMANENT upload to PostHog/pr-assets.\n"
    "   SHA-pinned URLs keep serving even after the file is deleted, so an upload cannot be taken back.\n"
    "   Never upload customer data, secrets, tokens, or internal-only information."
)


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


def upload(path: Path, key: str, token: str, session: requests.Session, message: str) -> str:
    """PUT the file to the contents API, returning the created commit sha.

    Retries once on HTTP 409 with the same key, since concurrent commits to the repo's
    default branch can race.
    """
    url = f"https://api.github.com/repos/{REPO}/contents/{key}"
    body = {"message": message, "content": _encode_base64(path)}

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
        f"upload of {path.name} was denied. Writing to {REPO} needs write access to a public PostHog repo: "
        "confirm your token is a PostHog org account with the `repo` scope "
        "(gh users: `gh auth refresh -s repo`; or set GH_TOKEN to a PAT with the repo scope)."
    )
