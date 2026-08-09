"""Storage for the public PostHog/pr-assets evidence repo.

pr:upload-image and pr:upload-video both publish here. This module owns every storage
concern behind a single call: sourcing a token, naming objects, committing them, and
handing back the URLs that render in a PR. Callers never see keys, commit shas, or the
GitHub API, so they cannot assemble a URL that does not exist.

Commits go through the GraphQL createCommitOnBranch mutation rather than the REST
contents API because the repo requires verified signatures. GraphQL commits under
GitHub's own signing key; the REST path commits as the caller, unsigned, and the
ruleset rejects it.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import click
import requests

from hogli_commands.github_auth import github_headers, github_token

REPO: Final = "PostHog/pr-assets"
_OWNER, _NAME = REPO.split("/")
_API: Final = "https://api.github.com/graphql"
# Each retry re-reads the branch head, and that round trip is the backoff.
_MAX_ATTEMPTS: Final = 5

PUBLIC_WARNING: Final = (
    "⚠  PUBLIC + PERMANENT upload to PostHog/pr-assets.\n"
    "   SHA-pinned URLs keep serving even after the file is deleted, so an upload cannot be taken back.\n"
    "   Never upload customer data, secrets, tokens, or internal-only information."
)

_HEAD_QUERY: Final = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { name target { oid } }
  }
}
"""

_COMMIT_MUTATION: Final = """
mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid } }
}
"""


@dataclass(frozen=True, kw_only=True)
class _Head:
    branch: str
    oid: str


class _OperationFailed(Exception):
    """A GraphQL response that carried an errors array."""

    def __init__(self, errors: Sequence[dict[str, Any]]) -> None:
        self.types = {error.get("type") for error in errors}
        self.messages = [str(error.get("message", "")) for error in errors]
        super().__init__("; ".join(self.messages))


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


def publish(paths: Sequence[Path], *, message: str) -> list[str]:
    """Commit every path in one signed commit, returning a raw URL per path in input order.

    URLs are pinned to the created commit, so they keep serving even after the file is
    moved or deleted.
    """
    token = github_token()
    if token is None:
        raise click.ClickException(
            "no GitHub token found. Set GH_TOKEN or GITHUB_TOKEN, or install gh "
            "(https://cli.github.com/) and run `gh auth login`."
        )
    additions = [
        {"path": make_key(path.suffix.lower().lstrip(".")), "contents": _encode_base64(path)} for path in paths
    ]
    oid = _commit(requests.Session(), token, additions, message)
    return [f"https://raw.githubusercontent.com/{REPO}/{oid}/{addition['path']}" for addition in additions]


def _encode_base64(path: Path) -> str:
    """Base64-encode the file as a single newline-free line.

    GraphQL wants raw base64 with no line breaks; ``b64encode`` (unlike ``encodebytes``)
    never inserts them.
    """
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _graphql(session: requests.Session, token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """POST a GraphQL document and return its ``data``.

    GraphQL answers HTTP 200 even when the operation fails, so the errors array decides
    the outcome and the status code only catches transport and auth failures.
    """
    try:
        resp = session.post(
            _API, headers=github_headers(token), json={"query": query, "variables": variables}, timeout=120
        )
    except requests.RequestException as exc:
        raise click.ClickException(f"GitHub request failed: {exc}")

    if resp.status_code in (401, 403):
        raise click.ClickException(_denied_message())
    if not resp.ok:
        raise click.ClickException(f"GitHub returned HTTP {resp.status_code}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise click.ClickException(f"GitHub returned a non-JSON response: {exc}")

    if errors := body.get("errors"):
        raise _OperationFailed(errors)
    data = body.get("data")
    if not isinstance(data, dict):
        raise click.ClickException("GitHub returned a response carrying no data")
    return data


def _read_head(session: requests.Session, token: str) -> _Head:
    # _OperationFailed is the retry signal for the mutation; a failed read has nothing to retry.
    try:
        data = _graphql(session, token, _HEAD_QUERY, {"owner": _OWNER, "name": _NAME})
    except _OperationFailed as exc:
        raise click.ClickException(f"could not read {REPO}: {exc}")
    ref = (data.get("repository") or {}).get("defaultBranchRef") or {}
    branch, oid = ref.get("name"), (ref.get("target") or {}).get("oid")
    if not branch or not oid:
        raise click.ClickException(f"could not read the default branch of {REPO}")
    return _Head(branch=branch, oid=oid)


def _commit(session: requests.Session, token: str, additions: list[dict[str, str]], message: str) -> str:
    """Create one signed commit carrying every addition, returning its oid.

    The mutation names the head it expects to extend, so a commit that lands first fails
    this one with STALE_DATA and re-reading the head is the whole recovery. Committing
    every file together keeps that rare: one invocation makes one commit.
    """
    head = _read_head(session, token)
    for _ in range(_MAX_ATTEMPTS):
        variables = {
            "input": {
                "branch": {"repositoryNameWithOwner": REPO, "branchName": head.branch},
                "message": {"headline": message},
                "expectedHeadOid": head.oid,
                "fileChanges": {"additions": additions},
            }
        }
        try:
            data = _graphql(session, token, _COMMIT_MUTATION, variables)
        except _OperationFailed as exc:
            if "STALE_DATA" in exc.types:
                head = _read_head(session, token)
                continue
            # The head read above resolved this branch, so GitHub calling it missing here
            # means the token can read the repo but not write to it.
            if any("Branch not found" in reported for reported in exc.messages):
                raise click.ClickException(_denied_message())
            raise click.ClickException(f"upload failed: {exc}")

        oid = ((data.get("createCommitOnBranch") or {}).get("commit") or {}).get("oid")
        if not oid:
            raise click.ClickException("GitHub returned a commit carrying no sha")
        return oid

    raise click.ClickException(
        f"{REPO} moved under the upload {_MAX_ATTEMPTS} times in a row; nothing was published, so try again"
    )


def _denied_message() -> str:
    """Explain a rejected write: the token can't write to pr-assets (not an org member, or missing scope)."""
    return (
        f"upload denied. Writing to {REPO} needs write access to a public PostHog repo: "
        "confirm your token is a PostHog org account with the `repo` scope "
        "(gh users: `gh auth refresh -s repo`; or set GH_TOKEN to a PAT with the repo scope)."
    )
