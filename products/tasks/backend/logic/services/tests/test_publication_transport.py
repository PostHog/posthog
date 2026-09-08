import hashlib
from datetime import UTC, datetime
from typing import cast

import pytest

import requests

from products.tasks.backend.logic.services.publication_transport import (
    BranchCreation,
    DraftPullRequest,
    NormalizedTreeOperation,
    PublicationAmbiguousError,
    PublicationConflictError,
    PublicationTransportError,
    PublicationTransportInput,
    create_draft_pull_request,
    create_server_branch,
    create_server_commit,
    read_draft_pull_request_state,
    reconcile_draft_pull_request,
    reconcile_server_branch,
)

BASE = "a" * 40
BASE_TREE = "b" * 40
HEAD_TREE = "c" * 40
COMMIT = "d" * 40


class _NonJsonResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def json(self) -> object:
        raise ValueError("transient response has no JSON body")


def _blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def _input() -> PublicationTransportInput:
    return PublicationTransportInput(
        repository="example/repository",
        base_sha=BASE,
        base_branch="main",
        head_branch="codex/tasks-draft-0123456789abcdef0123456789abcdef",
        commit_message="feat(tasks): publish fixture",
        commit_author_name="PostHog Tasks",
        commit_author_email="tasks@posthog.com",
        commit_timestamp=1_700_000_000,
        expected_base_tree_sha=BASE_TREE,
        expected_head_tree_sha=HEAD_TREE,
        operations=(NormalizedTreeOperation(path="safe.txt", mode="100644", content=b"safe\n"),),
        title="Publish fixture",
        body="Synthetic body",
    )


class FakeGitHubClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.branch_sha: str | None = None
        self.pull_request: dict[str, object] | None = None
        self.ambiguous_branch = False
        self.ambiguous_pr = False
        self.malformed_branch = False
        self.malformed_pr = False
        self.branch_status: int | None = None
        self.pr_status: int | None = None
        self.read_status: int | None = None
        self.read_response: object | None = None
        self.mutation_response: object | None = None
        self.current_base = BASE
        self.base_is_descendant = True
        self.returned_tree = HEAD_TREE

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
    ) -> object:
        self.requests.append((method, path))
        publication = _input()
        if method == "GET" and self.read_response is not None:
            return self.read_response
        if method == "GET" and self.read_status is not None:
            return _NonJsonResponse(self.read_status)
        if method == "POST" and self.mutation_response is not None:
            return self.mutation_response
        if method == "GET" and path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": self.current_base}}
        if method == "GET" and "/compare/" in path:
            return {
                "status": "ahead" if self.base_is_descendant else "diverged",
                "merge_base_commit": {"sha": BASE if self.base_is_descendant else "e" * 40},
            }
        if method == "GET" and path.endswith(f"/git/commits/{BASE}"):
            return {"sha": BASE, "tree": {"sha": BASE_TREE}}
        if method == "POST" and path.endswith("/git/blobs"):
            return {"sha": _blob_sha(b"safe\n")}
        if method == "POST" and path.endswith("/git/trees"):
            return {"sha": self.returned_tree}
        if method == "POST" and path.endswith("/git/commits"):
            return {"sha": COMMIT}
        if method == "GET" and path.endswith(f"/git/commits/{COMMIT}"):
            identity = {
                "name": publication.commit_author_name,
                "email": publication.commit_author_email,
                "date": datetime.fromtimestamp(publication.commit_timestamp, UTC).isoformat().replace("+00:00", "Z"),
            }
            return {
                "sha": COMMIT,
                "message": publication.commit_message,
                "tree": {"sha": HEAD_TREE},
                "parents": [
                    {"sha": BASE, "url": "https://api.github.com/commit", "html_url": "https://github.com/commit"}
                ],
                "author": identity,
                "committer": identity,
            }
        if method == "POST" and path.endswith("/git/refs"):
            if self.branch_status is not None:
                return {"status_code": self.branch_status}
            self.branch_sha = str((json_body or {})["sha"])
            if self.ambiguous_branch:
                raise TimeoutError("accepted then disconnected")
            if self.malformed_branch:
                return {}
            return {"ref": f"refs/heads/{publication.head_branch}", "object": {"sha": self.branch_sha}}
        if method == "GET" and "/git/ref/heads/codex/" in path:
            return {"object": {"sha": self.branch_sha}} if self.branch_sha else {"status_code": 404}
        if method == "POST" and path.endswith("/pulls"):
            if self.pr_status is not None:
                return {"status_code": self.pr_status}
            self.pull_request = _draft_payload(publication)
            if self.ambiguous_pr:
                raise TimeoutError("accepted then disconnected")
            if self.malformed_pr:
                return {}
            return self.pull_request
        if method == "GET" and "/pulls/" in path:
            return self.pull_request or {}
        if method == "GET" and path.endswith("/pulls"):
            return [self.pull_request] if self.pull_request else []
        raise AssertionError(f"unexpected request: {method} {path}")


def _draft_payload(publication: PublicationTransportInput) -> dict[str, object]:
    return {
        "number": 17,
        "html_url": "https://github.com/Example/Repository/pull/17",
        "draft": True,
        "state": "open",
        "title": publication.title,
        "body": publication.body,
        "base": {"ref": publication.base_branch, "sha": BASE, "repo": {"full_name": "Example/Repository"}},
        "head": {
            "ref": publication.head_branch,
            "sha": COMMIT,
            "repo": {"full_name": "Example/Repository"},
        },
    }


def test_server_materializes_commit_new_ref_and_draft_pr_in_order() -> None:
    client = FakeGitHubClient()
    publication = _input()

    commit = create_server_commit(client, publication)
    branch = create_server_branch(client, publication, commit)
    pull_request = create_draft_pull_request(client, publication, commit)

    assert commit == COMMIT
    assert branch == BranchCreation.CREATED
    assert pull_request == DraftPullRequest(number=17, url="https://github.com/Example/Repository/pull/17")
    mutations = [path for method, path in client.requests if method == "POST"]
    assert mutations == [
        "/repos/example/repository/git/blobs",
        "/repos/example/repository/git/trees",
        "/repos/example/repository/git/commits",
        "/repos/example/repository/git/refs",
        "/repos/example/repository/pulls",
    ]


@pytest.mark.parametrize("operation", ["branch-timeout", "branch-response", "pr-timeout", "pr-response"])
def test_ambiguous_mutation_is_reconciled_read_only_without_second_create(operation: str) -> None:
    client = FakeGitHubClient()
    publication = _input()
    kind, outcome = operation.split("-")
    if kind == "branch":
        setattr(client, f"{'ambiguous' if outcome == 'timeout' else 'malformed'}_branch", True)
        with pytest.raises(PublicationAmbiguousError):
            create_server_branch(client, publication, COMMIT)
        assert reconcile_server_branch(client, publication, expected_branch_sha=COMMIT) == BranchCreation.EXISTS_EXACT
        path = "/repos/example/repository/git/refs"
    else:
        client.branch_sha = COMMIT
        setattr(client, f"{'ambiguous' if outcome == 'timeout' else 'malformed'}_pr", True)
        with pytest.raises(PublicationAmbiguousError):
            create_draft_pull_request(client, publication, COMMIT)
        assert reconcile_draft_pull_request(client, publication, expected_branch_sha=COMMIT) == DraftPullRequest(
            number=17, url="https://github.com/Example/Repository/pull/17"
        )
        path = "/repos/example/repository/pulls"

    assert [request for request in client.requests if request == ("POST", path)] == [("POST", path)]


@pytest.mark.parametrize("operation", ["branch", "pr"])
def test_422_mutation_reconciles_the_existing_server_object(operation: str) -> None:
    client = FakeGitHubClient()
    client.branch_sha = COMMIT
    if operation == "branch":
        client.branch_status = 422
        assert create_server_branch(client, _input(), COMMIT) == BranchCreation.EXISTS_EXACT
    else:
        client.pr_status = 422
        client.pull_request = _draft_payload(_input())
        assert create_draft_pull_request(client, _input(), COMMIT).number == 17


@pytest.mark.parametrize("status_code", [408, 429, 500])
def test_transient_read_status_is_retryable_without_parsing_the_response(status_code: int) -> None:
    client = FakeGitHubClient()
    client.read_status = status_code

    with pytest.raises(PublicationTransportError) as error:
        create_server_commit(client, _input())

    assert type(error.value) is PublicationTransportError


@pytest.mark.parametrize(
    ("headers", "body"),
    [({"x-ratelimit-remaining": "0"}, ""), ({"retry-after": "60"}, ""), ({}, "API rate limit exceeded")],
)
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_rate_limited_403_response_is_retryable(method: str, headers: dict[str, str], body: str) -> None:
    response = requests.Response()
    response.status_code = 403
    response.headers.update(headers)
    response._content = body.encode()
    client = FakeGitHubClient()
    if method == "GET":
        client.read_response = response
    else:
        client.mutation_response = response

    with pytest.raises(PublicationTransportError) as error:
        create_server_commit(client, _input())

    assert type(error.value) is PublicationTransportError


def test_rate_limited_post_429_response_remains_ambiguous() -> None:
    response = requests.Response()
    response.status_code = 429
    client = FakeGitHubClient()
    client.mutation_response = response

    with pytest.raises(PublicationAmbiguousError):
        create_server_commit(client, _input())


def test_existing_branch_with_a_different_commit_is_blocked() -> None:
    client = FakeGitHubClient()
    client.branch_sha = "e" * 40

    with pytest.raises(PublicationConflictError):
        reconcile_server_branch(client, _input(), expected_branch_sha=COMMIT)


def test_non_draft_pull_request_is_blocked() -> None:
    client = FakeGitHubClient()
    client.branch_sha = COMMIT
    client.pull_request = {**_draft_payload(_input()), "draft": False}

    with pytest.raises(PublicationConflictError):
        reconcile_draft_pull_request(client, _input(), expected_branch_sha=COMMIT)


def test_current_base_fast_forward_is_accepted() -> None:
    client = FakeGitHubClient()
    client.current_base = "e" * 40

    assert create_server_commit(client, _input()) == COMMIT
    assert any("/compare/" in path for method, path in client.requests if method == "GET")


def test_rewritten_current_base_is_blocked_before_mutation() -> None:
    client = FakeGitHubClient()
    client.current_base = "e" * 40
    client.base_is_descendant = False

    with pytest.raises(PublicationConflictError):
        create_server_commit(client, _input())

    assert not any(method == "POST" for method, _path in client.requests)


def test_mismatched_materialized_head_tree_is_blocked_before_commit() -> None:
    client = FakeGitHubClient()
    client.returned_tree = "e" * 40

    with pytest.raises(PublicationConflictError):
        create_server_commit(client, _input())

    assert ("POST", "/repos/example/repository/git/commits") not in client.requests


def test_read_draft_pull_request_state_accepts_only_the_exact_published_pull_request() -> None:
    client = FakeGitHubClient()
    publication = _input()
    client.pull_request = _draft_payload(publication)
    assert client.pull_request is not None
    head = cast(dict[str, object], client.pull_request["head"])
    base = cast(dict[str, object], client.pull_request["base"])
    base_repo = cast(dict[str, object], base["repo"])
    head_repo = cast(dict[str, object], head["repo"])
    client.pull_request["state"] = "open"
    client.pull_request["merged"] = False
    head["sha"] = COMMIT
    base_repo["full_name"] = "Example/Repository"
    head_repo["full_name"] = "Example/Repository"
    client.pull_request["html_url"] = "https://github.com/example/repository/pull/17"

    assert (
        read_draft_pull_request_state(
            client,
            publication,
            pr_number=17,
            expected_pr_url="https://github.com/example/repository/pull/17",
            expected_commit_sha=COMMIT,
        )
        == "open"
    )
    assert client.requests == [("GET", "/repos/example/repository/pulls/17")]


def test_read_draft_pull_request_state_rejects_a_mismatched_remote_head() -> None:
    client = FakeGitHubClient()
    publication = _input()
    client.pull_request = _draft_payload(publication)
    assert client.pull_request is not None
    head = cast(dict[str, object], client.pull_request["head"])
    head["sha"] = "e" * 40

    with pytest.raises(PublicationTransportError, match="protected pull request"):
        read_draft_pull_request_state(
            client,
            publication,
            pr_number=17,
            expected_pr_url="https://github.com/Example/Repository/pull/17",
            expected_commit_sha=COMMIT,
        )
