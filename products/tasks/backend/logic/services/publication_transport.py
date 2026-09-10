"""GitHub egress boundary for a Tasks-owned draft pull request."""

from __future__ import annotations

import re
import hashlib
from dataclasses import field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

import requests

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError, github_request, raise_if_github_rate_limited
from posthog.egress.limiter.policies import Priority

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SERVER_BRANCH = re.compile(r"^codex/tasks-draft-[0-9a-f]{32}$")


class GitHubPublicationClient(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
    ) -> object: ...


class PublicationTransportError(RuntimeError):
    pass


class PublicationConflictError(PublicationTransportError):
    pass


class PublicationAmbiguousError(PublicationTransportError):
    pass


class PublicationRejectedError(PublicationTransportError):
    pass


class BranchCreation(StrEnum):
    CREATED = "created"
    EXISTS_EXACT = "exists_exact"


@frozen
class NormalizedTreeOperation:
    path: str
    mode: Literal["100644", "100755"]
    content: bytes | None


@frozen
class PublicationTransportInput:
    repository: str
    base_sha: str
    base_branch: str
    head_branch: str
    commit_message: str
    commit_author_name: str
    commit_author_email: str
    commit_timestamp: int
    expected_base_tree_sha: str
    expected_head_tree_sha: str
    operations: tuple[NormalizedTreeOperation, ...]
    title: str
    body: str


@frozen
class DraftPullRequest:
    number: int
    url: str


PullRequestState = Literal["open", "merged", "closed"]


@frozen
class ServerGitHubPublicationClient:
    installation_id: str
    token: str = field(repr=False)

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
    ) -> object:
        session = requests.Session()
        session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
        try:
            return github_request(
                method,
                f"https://api.github.com{path}",
                source="tasks_draft_publication",
                headers={"Authorization": f"Bearer {self.token}"},
                installation_id=self.installation_id,
                priority=Priority.CRITICAL,
                endpoint=path,
                json=json_body,
                params=params,
                timeout=(2, 20),
                session=session,
            )
        finally:
            session.close()


def _payload(response: object) -> object:
    if isinstance(response, (dict, list)):
        return response
    loader = getattr(response, "json", None)
    if not callable(loader):
        raise PublicationTransportError("GitHub returned an invalid response")
    return loader()


def _status(response: object) -> int | None:
    if isinstance(response, dict) and isinstance(response.get("status_code"), int):
        return response["status_code"]
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _request(
    client: GitHubPublicationClient,
    method: str,
    path: str,
    *,
    json_body: dict[str, object] | None = None,
    params: dict[str, str] | None = None,
    accepted_statuses: tuple[int, ...] = (),
) -> object:
    try:
        response = client.request(method, path, json_body=json_body, params=params)
    except (requests.RequestException, TimeoutError, ConnectionError) as err:
        if method == "POST":
            raise PublicationAmbiguousError("GitHub mutation outcome is unknown") from err
        raise PublicationTransportError("GitHub read failed") from err
    if isinstance(response, requests.Response) and response.status_code == 403:
        try:
            raise_if_github_rate_limited(response)
        except GitHubRateLimitError as err:
            raise PublicationTransportError("GitHub publication request was rate limited") from err
    status = _status(response)
    if status in {408, 429} or (status is not None and status >= 500):
        if method == "POST":
            raise PublicationAmbiguousError("GitHub mutation outcome is unknown")
        raise PublicationTransportError("GitHub read failed")
    if status is not None and 400 <= status < 500 and status not in {408, 429} and status not in accepted_statuses:
        raise PublicationRejectedError("GitHub deterministically rejected the publication request")
    return response


def _read_sha(response: object, label: str) -> str:
    payload = _payload(response)
    sha = payload.get("sha") if isinstance(payload, dict) else None
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise PublicationTransportError(f"GitHub returned an invalid {label} SHA")
    return sha


def _read_mutation_sha(response: object, label: str) -> str:
    try:
        return _read_sha(response, label)
    except PublicationTransportError as err:
        raise PublicationAmbiguousError(f"GitHub {label} creation outcome is unknown") from err


def _validate_input(publication: PublicationTransportInput) -> None:
    if (
        not _REPOSITORY.fullmatch(publication.repository)
        or not _SERVER_BRANCH.fullmatch(publication.head_branch)
        or not re.fullmatch(r"[A-Za-z0-9._/-]+", publication.base_branch)
        or publication.base_branch.startswith("/")
        or publication.base_branch.endswith("/")
        or ".." in publication.base_branch
        or "//" in publication.base_branch
    ):
        raise ValueError("Publication repository or branch is invalid")
    for value in (publication.base_sha, publication.expected_base_tree_sha, publication.expected_head_tree_sha):
        if not _SHA.fullmatch(value):
            raise ValueError("Publication Git identity is invalid")
    if not publication.operations or not publication.commit_message or not publication.title:
        raise ValueError("Publication input is incomplete")
    paths: set[str] = set()
    for operation in publication.operations:
        if (
            not operation.path
            or operation.path in paths
            or operation.path.startswith("/")
            or "\\" in operation.path
            or "\x00" in operation.path
            or any(part in {"", ".", ".."} for part in operation.path.split("/"))
        ):
            raise ValueError("Publication operation path is invalid")
        paths.add(operation.path)


def _validate_pull_request_read_input(publication: PublicationTransportInput) -> None:
    if (
        not _REPOSITORY.fullmatch(publication.repository)
        or not _SERVER_BRANCH.fullmatch(publication.head_branch)
        or not re.fullmatch(r"[A-Za-z0-9._/-]+", publication.base_branch)
        or publication.base_branch.startswith("/")
        or publication.base_branch.endswith("/")
        or ".." in publication.base_branch
        or "//" in publication.base_branch
    ):
        raise ValueError("Publication repository or branch is invalid")


def read_draft_pull_request_state(
    client: GitHubPublicationClient,
    publication: PublicationTransportInput,
    *,
    pr_number: int,
    expected_pr_url: str,
    expected_commit_sha: str,
) -> PullRequestState:
    """Read one protected draft PR, rejecting every identity mismatch."""
    _validate_pull_request_read_input(publication)
    if type(pr_number) is not int or pr_number <= 0 or not expected_pr_url or not _SHA.fullmatch(expected_commit_sha):
        raise ValueError("Protected pull request identity is invalid")
    response = _request(client, "GET", f"/repos/{publication.repository}/pulls/{pr_number}")
    payload = _payload(response)
    if _status(response) not in {None, 200} or not isinstance(payload, dict):
        raise PublicationTransportError("GitHub returned an invalid protected pull request")
    base = payload.get("base")
    head = payload.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    number = payload.get("number")
    url = payload.get("html_url")
    state = payload.get("state")
    merged = payload.get("merged")
    if (
        type(number) is not int
        or number != pr_number
        or not isinstance(url, str)
        or url != expected_pr_url
        or not isinstance(base, dict)
        or base.get("ref") != publication.base_branch
        or not isinstance(base_repo, dict)
        or not isinstance(base_repo.get("full_name"), str)
        or base_repo["full_name"].casefold() != publication.repository.casefold()
        or not isinstance(head, dict)
        or head.get("ref") != publication.head_branch
        or head.get("sha") != expected_commit_sha
        or not isinstance(head_repo, dict)
        or not isinstance(head_repo.get("full_name"), str)
        or head_repo["full_name"].casefold() != publication.repository.casefold()
    ):
        raise PublicationTransportError("GitHub returned a mismatched protected pull request")
    if state == "open" and merged is False:
        return "open"
    if state == "closed" and merged is True:
        return "merged"
    if state == "closed" and merged is False:
        return "closed"
    raise PublicationTransportError("GitHub returned an invalid protected pull request state")


def _current_base(client: GitHubPublicationClient, publication: PublicationTransportInput) -> str:
    response = _request(client, "GET", f"/repos/{publication.repository}/git/ref/heads/{publication.base_branch}")
    payload = _payload(response)
    object_data = payload.get("object") if isinstance(payload, dict) else None
    current = object_data.get("sha") if isinstance(object_data, dict) else None
    if _status(response) not in {None, 200} or not isinstance(current, str) or not _SHA.fullmatch(current):
        raise PublicationTransportError("GitHub rejected protected base lookup")
    if current == publication.base_sha:
        return current
    comparison_response = _request(
        client, "GET", f"/repos/{publication.repository}/compare/{publication.base_sha}...{current}"
    )
    comparison = _payload(comparison_response)
    merge_base = comparison.get("merge_base_commit") if isinstance(comparison, dict) else None
    if (
        _status(comparison_response) not in {None, 200}
        or not isinstance(comparison, dict)
        or comparison.get("status") not in {"ahead", "identical"}
        or not isinstance(merge_base, dict)
        or merge_base.get("sha") != publication.base_sha
    ):
        raise PublicationConflictError("Protected base no longer descends from the frozen base")
    return current


def _branch_tip(client: GitHubPublicationClient, publication: PublicationTransportInput) -> str | None:
    response = _request(
        client,
        "GET",
        f"/repos/{publication.repository}/git/ref/heads/{publication.head_branch}",
        accepted_statuses=(404,),
    )
    if _status(response) == 404:
        return None
    payload = _payload(response)
    object_data = payload.get("object") if isinstance(payload, dict) else None
    sha = object_data.get("sha") if isinstance(object_data, dict) else None
    if _status(response) not in {None, 200} or not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise PublicationTransportError("GitHub returned an invalid publication branch")
    return sha


def _commit_identity(publication: PublicationTransportInput) -> dict[str, str]:
    return {
        "name": publication.commit_author_name,
        "email": publication.commit_author_email,
        "date": datetime.fromtimestamp(publication.commit_timestamp, UTC).isoformat().replace("+00:00", "Z"),
    }


def create_server_commit(client: GitHubPublicationClient, publication: PublicationTransportInput) -> str:
    _validate_input(publication)
    _current_base(client, publication)
    base_response = _request(client, "GET", f"/repos/{publication.repository}/git/commits/{publication.base_sha}")
    base = _payload(base_response)
    tree = base.get("tree") if isinstance(base, dict) else None
    if (
        _status(base_response) not in {None, 200}
        or not isinstance(base, dict)
        or base.get("sha") != publication.base_sha
        or not isinstance(tree, dict)
        or tree.get("sha") != publication.expected_base_tree_sha
    ):
        raise PublicationConflictError("Frozen base tree does not match the normalized artifact")
    entries: list[dict[str, object]] = []
    for operation in publication.operations:
        if operation.content is None:
            entries.append({"path": operation.path, "mode": operation.mode, "type": "blob", "sha": None})
            continue
        _current_base(client, publication)
        response = _request(
            client,
            "POST",
            f"/repos/{publication.repository}/git/blobs",
            json_body={"content": operation.content.decode("utf-8"), "encoding": "utf-8"},
        )
        if _status(response) not in {None, 201}:
            raise PublicationTransportError("GitHub rejected publication blob creation")
        blob_sha = _read_mutation_sha(response, "blob")
        expected = (
            hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
                b"blob " + str(len(operation.content)).encode() + b"\0" + operation.content
            ).hexdigest()
        )
        if blob_sha != expected:
            raise PublicationConflictError("GitHub blob does not match normalized content")
        entries.append({"path": operation.path, "mode": operation.mode, "type": "blob", "sha": blob_sha})
    _current_base(client, publication)
    tree_response = _request(
        client,
        "POST",
        f"/repos/{publication.repository}/git/trees",
        json_body={"base_tree": publication.expected_base_tree_sha, "tree": entries},
    )
    if (
        _status(tree_response) not in {None, 201}
        or _read_mutation_sha(tree_response, "tree") != publication.expected_head_tree_sha
    ):
        raise PublicationConflictError("GitHub tree does not match normalized workspace head")
    _current_base(client, publication)
    commit_response = _request(
        client,
        "POST",
        f"/repos/{publication.repository}/git/commits",
        json_body={
            "message": publication.commit_message,
            "tree": publication.expected_head_tree_sha,
            "parents": [publication.base_sha],
            "author": _commit_identity(publication),
            "committer": _commit_identity(publication),
        },
    )
    if _status(commit_response) not in {None, 201}:
        raise PublicationTransportError("GitHub rejected publication commit creation")
    commit_sha = _read_mutation_sha(commit_response, "commit")
    verified_response = _request(client, "GET", f"/repos/{publication.repository}/git/commits/{commit_sha}")
    verified = _payload(verified_response)
    verified_tree = verified.get("tree") if isinstance(verified, dict) else None
    parents = verified.get("parents") if isinstance(verified, dict) else None
    if (
        _status(verified_response) not in {None, 200}
        or not isinstance(verified, dict)
        or verified.get("sha") != commit_sha
        or verified.get("message") != publication.commit_message
        or not isinstance(verified_tree, dict)
        or verified_tree.get("sha") != publication.expected_head_tree_sha
        or not isinstance(parents, list)
        or [parent.get("sha") if isinstance(parent, dict) else None for parent in parents] != [publication.base_sha]
        or verified.get("author") != _commit_identity(publication)
        or verified.get("committer") != _commit_identity(publication)
    ):
        raise PublicationConflictError("GitHub commit does not have the protected parent and tree")
    return commit_sha


def create_server_branch(
    client: GitHubPublicationClient, publication: PublicationTransportInput, commit_sha: str
) -> BranchCreation:
    _validate_input(publication)
    if not _SHA.fullmatch(commit_sha):
        raise ValueError("Publication commit SHA is invalid")
    _current_base(client, publication)
    response = _request(
        client,
        "POST",
        f"/repos/{publication.repository}/git/refs",
        json_body={"ref": f"refs/heads/{publication.head_branch}", "sha": commit_sha},
        accepted_statuses=(422,),
    )
    status = _status(response)
    if status == 422:
        return reconcile_server_branch(client, publication, expected_branch_sha=commit_sha) or _raise_branch_conflict()
    if status not in {None, 201}:
        if status in {408, 429} or (status is not None and status >= 500):
            raise PublicationAmbiguousError("GitHub branch creation outcome is unknown")
        raise PublicationTransportError("GitHub rejected publication branch creation")
    payload = _payload(response)
    object_data = payload.get("object") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("ref"), str)
        or not isinstance(object_data, dict)
        or not isinstance(object_data.get("sha"), str)
    ):
        raise PublicationAmbiguousError("GitHub branch creation outcome is unknown")
    if payload.get("ref") != f"refs/heads/{publication.head_branch}" or object_data.get("sha") != commit_sha:
        raise PublicationConflictError("GitHub returned a mismatched publication branch")
    if reconcile_server_branch(client, publication, expected_branch_sha=commit_sha) is None:
        raise PublicationConflictError("GitHub did not persist the publication branch")
    return BranchCreation.CREATED


def _raise_branch_conflict() -> BranchCreation:
    raise PublicationConflictError("Publication branch already exists with a different commit")


def reconcile_server_branch(
    client: GitHubPublicationClient, publication: PublicationTransportInput, *, expected_branch_sha: str
) -> BranchCreation | None:
    tip = _branch_tip(client, publication)
    if tip is None:
        return None
    if tip != expected_branch_sha:
        raise PublicationConflictError("Publication branch points to a different commit")
    return BranchCreation.EXISTS_EXACT


def _pull_request(
    payload: object, publication: PublicationTransportInput, expected_branch_sha: str, expected_base_sha: str
) -> DraftPullRequest:
    if not isinstance(payload, dict):
        raise PublicationTransportError("GitHub returned an invalid pull request")
    number = payload.get("number")
    base = payload.get("base")
    head = payload.get("head")
    base_repository = base.get("repo") if isinstance(base, dict) else None
    head_repository = head.get("repo") if isinstance(head, dict) else None
    if (
        not isinstance(number, int)
        or isinstance(number, bool)
        or number <= 0
        or not isinstance(payload.get("html_url"), str)
        or not isinstance(payload.get("draft"), bool)
        or not isinstance(payload.get("state"), str)
        or not isinstance(payload.get("title"), str)
        or not isinstance(payload.get("body"), (str, type(None)))
        or not isinstance(base, dict)
        or not isinstance(base.get("ref"), str)
        or not isinstance(base.get("sha"), str)
        or not isinstance(base_repository, dict)
        or not isinstance(base_repository.get("full_name"), str)
        or not isinstance(head, dict)
        or not isinstance(head.get("ref"), str)
        or not isinstance(head.get("sha"), str)
        or not isinstance(head_repository, dict)
        or not isinstance(head_repository.get("full_name"), str)
    ):
        raise PublicationTransportError("GitHub returned an invalid pull request")
    if (
        payload.get("draft") is not True
        or payload.get("state") != "open"
        or payload.get("title") != publication.title
        or (payload.get("body") or "") != publication.body
        or payload["html_url"].casefold() != f"https://github.com/{publication.repository}/pull/{number}".casefold()
        or base.get("ref") != publication.base_branch
        or base.get("sha") != expected_base_sha
        or base_repository["full_name"].casefold() != publication.repository.casefold()
        or head.get("ref") != publication.head_branch
        or head.get("sha") != expected_branch_sha
        or head_repository["full_name"].casefold() != publication.repository.casefold()
    ):
        raise PublicationConflictError("GitHub pull request does not match the protected draft claim")
    return DraftPullRequest(number=number, url=payload["html_url"])


def create_draft_pull_request(
    client: GitHubPublicationClient, publication: PublicationTransportInput, commit_sha: str
) -> DraftPullRequest:
    current_base = _current_base(client, publication)
    if reconcile_server_branch(client, publication, expected_branch_sha=commit_sha) is None:
        raise PublicationConflictError("Publication branch is not verified")
    response = _request(
        client,
        "POST",
        f"/repos/{publication.repository}/pulls",
        json_body={
            "title": publication.title,
            "body": publication.body,
            "head": publication.head_branch,
            "base": publication.base_branch,
            "draft": True,
        },
        accepted_statuses=(422,),
    )
    status = _status(response)
    if status == 422:
        reconciled = reconcile_draft_pull_request(client, publication, expected_branch_sha=commit_sha)
        if reconciled is not None:
            return reconciled
        raise PublicationConflictError("GitHub rejected draft pull request creation")
    if status not in {None, 201}:
        if status in {408, 429} or (status is not None and status >= 500):
            raise PublicationAmbiguousError("GitHub draft pull request outcome is unknown")
        raise PublicationTransportError("GitHub rejected draft pull request creation")
    try:
        return _pull_request(_payload(response), publication, commit_sha, current_base)
    except PublicationConflictError:
        raise
    except PublicationTransportError as err:
        raise PublicationAmbiguousError("GitHub draft pull request outcome is unknown") from err


def reconcile_draft_pull_request(
    client: GitHubPublicationClient, publication: PublicationTransportInput, *, expected_branch_sha: str
) -> DraftPullRequest | None:
    current_base = _current_base(client, publication)
    if reconcile_server_branch(client, publication, expected_branch_sha=expected_branch_sha) is None:
        return None
    owner = publication.repository.partition("/")[0]
    response = _request(
        client,
        "GET",
        f"/repos/{publication.repository}/pulls",
        params={"head": f"{owner}:{publication.head_branch}", "state": "all", "per_page": "100"},
    )
    if _status(response) not in {None, 200}:
        raise PublicationTransportError("GitHub rejected pull request reconciliation")
    payload = _payload(response)
    if not isinstance(payload, list):
        raise PublicationTransportError("GitHub returned an invalid pull request list")
    if not payload:
        return None
    if len(payload) != 1:
        raise PublicationConflictError("Multiple pull requests use the publication branch")
    return _pull_request(payload[0], publication, expected_branch_sha, current_base)
