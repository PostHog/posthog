"""Narrow GitHub transport for one Tasks-owned draft pull request."""

from __future__ import annotations

import re
import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

import requests

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationError

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SERVER_BRANCH_RE = re.compile(r"^codex/[0-9a-f]{32}$")


class GitHubResponse(Protocol):
    status_code: int

    def json(self) -> object: ...


class GitHubPublicationClient(Protocol):
    def api_request(
        self,
        method: str,
        path: str,
        *,
        endpoint: str | None = None,
        params: dict[str, str | int] | None = None,
        json_body: dict[str, object] | None = None,
        priority: Priority | None = None,
        retry_transient: bool | None = None,
    ) -> GitHubResponse: ...


class PublicationTransportError(RuntimeError):
    pass


class PublicationConflictError(PublicationTransportError):
    pass


class ClosedPublicationError(PublicationTransportError):
    pass


class PublicationAmbiguousError(PublicationTransportError):
    """A GitHub mutation may have succeeded, so the caller must reconcile only."""


class BranchCreation(StrEnum):
    CREATED = "created"
    EXISTS_EXACT = "exists_exact"


@frozen
class NormalizedTreeOperation:
    """One trusted normalized text-file update or deletion from the bundle validator."""

    path: str
    mode: Literal["100644", "100755"]
    content: bytes | None


@frozen
class DraftPublicationInput:
    repository: str
    base_sha: str
    base_branch: str
    branch: str
    expected_creator_login: str
    expected_github_app_slug: str
    commit_message: str
    commit_author_name: str
    commit_author_email: str
    commit_timestamp: int
    title: str
    body: str
    operations: tuple[NormalizedTreeOperation, ...]


@frozen
class DraftPullRequest:
    commit_sha: str
    pr_number: int
    pr_url: str


def create_server_commit(client: GitHubPublicationClient, publication: DraftPublicationInput) -> str:
    """Create and verify a one-parent server commit before publishing its ref."""
    _validate_input(publication)
    base_tree_sha = _read_base_tree(client, publication)
    tree_sha = _create_tree(client, publication, base_tree_sha)
    commit_sha = _create_commit(client, publication, tree_sha)
    _verify_created_commit(client, publication, commit_sha, tree_sha)
    return commit_sha


def create_server_branch(
    client: GitHubPublicationClient, publication: DraftPublicationInput, commit_sha: str
) -> BranchCreation:
    """Create the exact branch once, never force-update it, and expose races to the caller."""
    _validate_input(publication)
    _validate_sha(commit_sha, "commit_sha")
    existing = _read_branch_tip(client, publication)
    if existing is not None:
        if existing != commit_sha:
            raise PublicationConflictError("server publication branch already exists with a different commit")
        return BranchCreation.EXISTS_EXACT

    _validate_base_branch_tip(client, publication)
    response = _mutation_request(
        client,
        "POST",
        f"/repos/{publication.repository}/git/refs",
        operation="branch creation",
        endpoint="/repos/{owner}/{repo}/git/refs",
        json_body={"ref": f"refs/heads/{publication.branch}", "sha": commit_sha},
    )
    if response.status_code == 201:
        payload = response.json()
        object_data = payload.get("object") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("ref") != f"refs/heads/{publication.branch}"
            or not isinstance(object_data, dict)
            or object_data.get("sha") != commit_sha
        ):
            raise PublicationConflictError("GitHub returned a mismatched server publication branch")
        return BranchCreation.CREATED
    if response.status_code == 422:
        existing = _read_branch_tip(client, publication)
        if existing == commit_sha:
            return BranchCreation.EXISTS_EXACT
        raise PublicationConflictError("server publication branch already exists with a different commit")
    if response.status_code == 408 or response.status_code >= 500:
        raise PublicationAmbiguousError(f"GitHub branch creation outcome is unknown ({response.status_code})")
    raise PublicationTransportError(f"GitHub rejected server publication branch creation ({response.status_code})")


def create_draft_pull_request(
    client: GitHubPublicationClient, publication: DraftPublicationInput, commit_sha: str
) -> DraftPullRequest:
    """Create one draft PR after the state layer has durably recorded branch creation."""
    _validate_input(publication)
    _validate_sha(commit_sha, "commit_sha")
    _validate_base_branch_tip(client, publication)
    response = _mutation_request(
        client,
        "POST",
        f"/repos/{publication.repository}/pulls",
        operation="draft pull request creation",
        endpoint="/repos/{owner}/{repo}/pulls",
        json_body={
            "title": publication.title,
            "body": publication.body,
            "head": publication.branch,
            "base": publication.base_branch,
            "draft": True,
        },
    )
    if response.status_code == 201:
        return _validated_pull_request_payload(client, response.json(), publication, expected_branch_sha=commit_sha)
    if response.status_code == 422:
        reconciled = reconcile_draft_pull_request(client, publication, expected_branch_sha=commit_sha)
        if reconciled is not None:
            return reconciled
        raise PublicationConflictError("GitHub rejected draft pull request creation")
    if response.status_code == 408 or response.status_code >= 500:
        raise PublicationAmbiguousError(f"GitHub draft pull request outcome is unknown ({response.status_code})")
    raise PublicationTransportError(f"GitHub rejected draft pull request creation ({response.status_code})")


def reconcile_draft_pull_request(
    client: GitHubPublicationClient,
    publication: DraftPublicationInput,
    *,
    expected_branch_sha: str,
) -> DraftPullRequest | None:
    """Read existing server artifacts only. This function never creates a GitHub resource."""
    _validate_input(publication)
    _validate_sha(expected_branch_sha, "expected_branch_sha")
    branch_tip = _read_branch_tip(client, publication)
    if branch_tip is None:
        return None
    if branch_tip != expected_branch_sha:
        raise PublicationConflictError("server publication branch has moved")

    owner = publication.repository.partition("/")[0]
    response = _request(
        client,
        "GET",
        f"/repos/{publication.repository}/pulls",
        endpoint="/repos/{owner}/{repo}/pulls",
        params={"head": f"{owner}:{publication.branch}", "state": "all", "per_page": 100},
    )
    if response.status_code != 200:
        raise PublicationTransportError(f"GitHub rejected draft pull request reconciliation ({response.status_code})")
    payload = response.json()
    if not isinstance(payload, list):
        raise PublicationTransportError("GitHub returned an invalid pull request list")
    if not payload:
        return None
    if len(payload) != 1:
        raise PublicationConflictError("multiple pull requests use the server publication branch")
    return _validated_pull_request_payload(client, payload[0], publication, expected_branch_sha=expected_branch_sha)


def reconcile_server_branch(
    client: GitHubPublicationClient, publication: DraftPublicationInput, *, expected_branch_sha: str
) -> BranchCreation | None:
    """Read a server branch without mutating it, returning only an exact match."""
    _validate_input(publication)
    _validate_sha(expected_branch_sha, "expected_branch_sha")
    branch_tip = _read_branch_tip(client, publication)
    if branch_tip is None:
        return None
    if branch_tip != expected_branch_sha:
        raise PublicationConflictError("server publication branch has moved")
    return BranchCreation.EXISTS_EXACT


def _validate_input(publication: DraftPublicationInput) -> None:
    if not _REPOSITORY_RE.fullmatch(publication.repository):
        raise ValueError("repository must be an exact owner/name value")
    _validate_sha(publication.base_sha, "base_sha")
    if not _SERVER_BRANCH_RE.fullmatch(publication.branch):
        raise ValueError("branch must be the server-owned codex lease branch")
    if not _is_safe_branch_ref(publication.base_branch):
        raise ValueError("base_branch must be a normalized branch name")
    if (
        not publication.expected_creator_login
        or not publication.expected_github_app_slug
        or not publication.commit_message
        or not publication.commit_author_name
        or not publication.commit_author_email
        or not publication.title
        or not publication.operations
    ):
        raise ValueError("draft publication requires trusted creator identity, commit metadata, title, and operations")
    if not isinstance(publication.commit_timestamp, int) or not 0 < publication.commit_timestamp < 2**31:
        raise ValueError("commit_timestamp must be a bounded Unix timestamp")
    paths: set[str] = set()
    for operation in publication.operations:
        if (
            not operation.path
            or operation.path.startswith("/")
            or "\x00" in operation.path
            or "\\" in operation.path
            or any(component in {"", ".", ".."} for component in operation.path.split("/"))
        ):
            raise ValueError("normalized operation path is invalid")
        if operation.path in paths:
            raise ValueError("normalized operations may not target one path twice")
        paths.add(operation.path)
        if operation.mode not in {"100644", "100755"}:
            raise ValueError("normalized operation mode is invalid")
        if operation.content is not None and not isinstance(operation.content, bytes):
            raise ValueError("normalized operation content must be bytes or a deletion")


def _validate_sha(value: str, name: str) -> None:
    if not _SHA_RE.fullmatch(value):
        raise ValueError(f"{name} must be a full lowercase SHA")


def _is_safe_branch_ref(value: str) -> bool:
    if (
        not value
        or value == "@"
        or value.startswith(("/", "."))
        or value.endswith(("/", "."))
        or "@{" in value
        or ".." in value
        or "//" in value
        or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
        or any(character in "~^:?*[\\" for character in value)
    ):
        return False
    return all(not component.endswith(".lock") for component in value.split("/"))


def _request(
    client: GitHubPublicationClient,
    method: str,
    path: str,
    *,
    endpoint: str,
    params: dict[str, str | int] | None = None,
    json_body: dict[str, object] | None = None,
) -> GitHubResponse:
    return client.api_request(
        method,
        path,
        endpoint=endpoint,
        params=params,
        json_body=json_body,
        priority=Priority.CRITICAL,
        retry_transient=False,
    )


def _mutation_request(
    client: GitHubPublicationClient,
    method: str,
    path: str,
    *,
    operation: str,
    endpoint: str,
    json_body: dict[str, object],
) -> GitHubResponse:
    try:
        return _request(client, method, path, endpoint=endpoint, json_body=json_body)
    except (GitHubIntegrationError, requests.RequestException, TimeoutError) as error:
        raise PublicationAmbiguousError(f"GitHub {operation} outcome is unknown") from error


def _read_branch_tip(client: GitHubPublicationClient, publication: DraftPublicationInput) -> str | None:
    response = _request(
        client,
        "GET",
        f"/repos/{publication.repository}/git/ref/heads/{publication.branch}",
        endpoint="/repos/{owner}/{repo}/git/ref/heads/{branch}",
    )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise PublicationTransportError(f"GitHub rejected draft publication branch lookup ({response.status_code})")
    payload = response.json()
    object_data = payload.get("object") if isinstance(payload, dict) else None
    sha = object_data.get("sha") if isinstance(object_data, dict) else None
    if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
        raise PublicationTransportError("GitHub returned an invalid branch SHA")
    return sha


def _validate_base_branch_tip(client: GitHubPublicationClient, publication: DraftPublicationInput) -> None:
    response = _request(
        client,
        "GET",
        f"/repos/{publication.repository}/git/ref/heads/{publication.base_branch}",
        endpoint="/repos/{owner}/{repo}/git/ref/heads/{branch}",
    )
    payload = response.json()
    object_data = payload.get("object") if isinstance(payload, dict) else None
    tip_sha = object_data.get("sha") if isinstance(object_data, dict) else None
    if response.status_code != 200 or tip_sha != publication.base_sha:
        raise PublicationConflictError("protected base branch no longer matches the publication claim")


def _read_base_tree(client: GitHubPublicationClient, publication: DraftPublicationInput) -> str:
    response = _request(
        client,
        "GET",
        f"/repos/{publication.repository}/git/commits/{publication.base_sha}",
        endpoint="/repos/{owner}/{repo}/git/commits/{commit_sha}",
    )
    if response.status_code != 200:
        raise PublicationConflictError("protected base commit is unavailable")
    payload = response.json()
    tree = payload.get("tree") if isinstance(payload, dict) else None
    sha = tree.get("sha") if isinstance(tree, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("sha") != publication.base_sha
        or not isinstance(sha, str)
        or not _SHA_RE.fullmatch(sha)
    ):
        raise PublicationConflictError("GitHub returned a mismatched protected base commit")
    return sha


def _create_tree(client: GitHubPublicationClient, publication: DraftPublicationInput, base_tree_sha: str) -> str:
    entries: list[dict[str, object]] = []
    for operation in sorted(publication.operations, key=lambda item: item.path):
        if operation.content is None:
            entries.append({"path": operation.path, "mode": operation.mode, "type": "blob", "sha": None})
            continue
        try:
            text = operation.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("normalized operation content must be valid UTF-8") from error
        _validate_base_branch_tip(client, publication)
        blob_response = _request(
            client,
            "POST",
            f"/repos/{publication.repository}/git/blobs",
            endpoint="/repos/{owner}/{repo}/git/blobs",
            json_body={"content": text, "encoding": "utf-8"},
        )
        if blob_response.status_code != 201:
            raise PublicationTransportError(
                f"GitHub rejected draft publication blob creation ({blob_response.status_code})"
            )
        blob_sha = _read_sha(blob_response, "blob")
        # Git object IDs use SHA-1 by protocol, not for authentication.
        expected_blob_sha = (
            hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
                b"blob " + str(len(operation.content)).encode("ascii") + b"\0" + operation.content
            ).hexdigest()
        )
        if blob_sha != expected_blob_sha:
            raise PublicationConflictError("GitHub blob response did not match the trusted operation content")
        entries.append({"path": operation.path, "mode": operation.mode, "type": "blob", "sha": blob_sha})
    _validate_base_branch_tip(client, publication)
    response = _request(
        client,
        "POST",
        f"/repos/{publication.repository}/git/trees",
        endpoint="/repos/{owner}/{repo}/git/trees",
        json_body={"base_tree": base_tree_sha, "tree": entries},
    )
    if response.status_code != 201:
        raise PublicationTransportError(f"GitHub rejected draft publication tree creation ({response.status_code})")
    return _read_sha(response, "tree")


def _create_commit(client: GitHubPublicationClient, publication: DraftPublicationInput, tree_sha: str) -> str:
    _validate_base_branch_tip(client, publication)
    response = _request(
        client,
        "POST",
        f"/repos/{publication.repository}/git/commits",
        endpoint="/repos/{owner}/{repo}/git/commits",
        json_body={
            "message": publication.commit_message,
            "tree": tree_sha,
            "parents": [publication.base_sha],
            "author": _commit_identity(publication),
            "committer": _commit_identity(publication),
        },
    )
    if response.status_code != 201:
        raise PublicationTransportError(f"GitHub rejected draft publication commit creation ({response.status_code})")
    return _read_sha(response, "commit")


def _commit_identity(publication: DraftPublicationInput) -> dict[str, str]:
    return {
        "name": publication.commit_author_name,
        "email": publication.commit_author_email,
        "date": datetime.fromtimestamp(publication.commit_timestamp, UTC).isoformat().replace("+00:00", "Z"),
    }


def _verify_created_commit(
    client: GitHubPublicationClient, publication: DraftPublicationInput, commit_sha: str, tree_sha: str
) -> None:
    response = _request(
        client,
        "GET",
        f"/repos/{publication.repository}/git/commits/{commit_sha}",
        endpoint="/repos/{owner}/{repo}/git/commits/{commit_sha}",
    )
    if response.status_code != 200:
        raise PublicationTransportError("GitHub could not verify the server publication commit")
    payload = response.json()
    tree = payload.get("tree") if isinstance(payload, dict) else None
    parents = payload.get("parents") if isinstance(payload, dict) else None
    author = payload.get("author") if isinstance(payload, dict) else None
    committer = payload.get("committer") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("sha") != commit_sha
        or payload.get("message") != publication.commit_message
        or not isinstance(tree, dict)
        or tree.get("sha") != tree_sha
        or not isinstance(parents, list)
        or len(parents) != 1
        or not isinstance(parents[0], dict)
        or parents[0].get("sha") != publication.base_sha
        or author != _commit_identity(publication)
        or committer != _commit_identity(publication)
    ):
        raise PublicationConflictError("GitHub server publication commit does not have the protected parent and tree")


def _read_sha(response: GitHubResponse, object_type: str) -> str:
    payload = response.json()
    sha = payload.get("sha") if isinstance(payload, dict) else None
    if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
        raise PublicationTransportError(f"GitHub returned an invalid {object_type} SHA")
    return sha


def _validated_pull_request_payload(
    client: GitHubPublicationClient,
    payload: object,
    publication: DraftPublicationInput,
    *,
    expected_branch_sha: str,
) -> DraftPullRequest:
    if not isinstance(payload, dict):
        raise PublicationTransportError("GitHub returned an invalid pull request response")
    number = payload.get("number")
    url = payload.get("html_url")
    base = payload.get("base")
    head = payload.get("head")
    creator = payload.get("user")
    github_app = payload.get("performed_via_github_app")
    body = payload.get("body")
    if (
        not isinstance(number, int)
        or number <= 0
        or url != f"https://github.com/{publication.repository}/pull/{number}"
    ):
        raise PublicationTransportError("GitHub returned an invalid pull request identity")
    if payload.get("draft") is not True or payload.get("state") != "open":
        raise ClosedPublicationError("GitHub pull request is not an open draft")
    if body is None:
        body = ""
    if payload.get("title") != publication.title or not isinstance(body, str) or body != publication.body:
        raise PublicationConflictError("GitHub pull request text does not match the scanned publication claim")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise PublicationTransportError("GitHub returned an invalid pull request binding")
    if not isinstance(creator, dict) or creator.get("login") != publication.expected_creator_login:
        raise PublicationConflictError("GitHub pull request creator does not match the publication claim")
    if github_app is not None and (
        not isinstance(github_app, dict) or github_app.get("slug") != publication.expected_github_app_slug
    ):
        raise PublicationConflictError("GitHub pull request app does not match the publication claim")
    if (
        base.get("ref") != publication.base_branch
        or not isinstance(base.get("sha"), str)
        or not _SHA_RE.fullmatch(base["sha"])
        or head.get("ref") != publication.branch
        or head.get("sha") != expected_branch_sha
    ):
        raise PublicationConflictError("GitHub pull request bindings do not match the publication claim")
    base_repo = base.get("repo")
    head_repo = head.get("repo")
    if (
        not isinstance(base_repo, dict)
        or not isinstance(head_repo, dict)
        or base_repo.get("full_name") != publication.repository
        or head_repo.get("full_name") != publication.repository
    ):
        raise PublicationConflictError("GitHub pull request repository does not match the publication claim")
    _validate_pull_request_base_ancestry(client, publication, base["sha"])
    return DraftPullRequest(commit_sha=expected_branch_sha, pr_number=number, pr_url=url)


def _validate_pull_request_base_ancestry(
    client: GitHubPublicationClient, publication: DraftPublicationInput, current_base_sha: str
) -> None:
    if current_base_sha == publication.base_sha:
        return
    response = _request(
        client,
        "GET",
        f"/repos/{publication.repository}/compare/{publication.base_sha}...{current_base_sha}",
        endpoint="/repos/{owner}/{repo}/compare/{basehead}",
    )
    payload = response.json()
    base_commit = payload.get("base_commit") if isinstance(payload, dict) else None
    merge_base = payload.get("merge_base_commit") if isinstance(payload, dict) else None
    if (
        response.status_code != 200
        or not isinstance(payload, dict)
        or payload.get("status") not in {"ahead", "identical"}
        or payload.get("behind_by") != 0
        or not isinstance(payload.get("ahead_by"), int)
        or payload["ahead_by"] < 0
        or not isinstance(base_commit, dict)
        or base_commit.get("sha") != publication.base_sha
        or not isinstance(merge_base, dict)
        or merge_base.get("sha") != publication.base_sha
    ):
        raise PublicationConflictError("draft pull request base no longer descends from the protected base")
