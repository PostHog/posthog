import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import pytest

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority

from products.tasks.backend.logic.services.publication_transport import (
    BranchCreation,
    ClosedPublicationError,
    DraftPublicationInput,
    NormalizedTreeOperation,
    PublicationAmbiguousError,
    PublicationConflictError,
    create_draft_pull_request,
    create_server_branch,
    create_server_commit,
    reconcile_draft_pull_request,
)


@dataclass(frozen=False)
class _Response:
    status_code: int
    body: object

    def json(self) -> object:
        return self.body


class _GitHubFake:
    def __init__(self, responses: Mapping[tuple[str, str], list[_Response | Exception]]) -> None:
        self.responses = {key: list(value) for key, value in responses.items()}
        self.requests: list[tuple[str, str, dict[str, object]]] = []

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
    ) -> _Response:
        kwargs: dict[str, object] = {
            "endpoint": endpoint,
            "params": params,
            "json_body": json_body,
            "priority": priority,
            "retry_transient": retry_transient,
        }
        self.requests.append((method, path, kwargs))
        response = self.responses[(method, path)].pop(0)
        if isinstance(response, Exception):
            raise response
        return response


REPOSITORY = "posthog/posthog"
BASE_SHA = "a" * 40
BRANCH = "codex/0123456789abcdef0123456789abcdef"
COMMIT_SHA = "c" * 40
CREATOR_LOGIN = "posthog-app[bot]"
GITHUB_APP_SLUG = "posthog"
COMMIT_AUTHOR = "PostHog Tasks"
COMMIT_AUTHOR_EMAIL = "tasks@posthog.com"
COMMIT_TIMESTAMP = 1_000


def _blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def _publication() -> DraftPublicationInput:
    return DraftPublicationInput(
        repository=REPOSITORY,
        base_sha=BASE_SHA,
        base_branch="main",
        branch=BRANCH,
        expected_creator_login=CREATOR_LOGIN,
        expected_github_app_slug=GITHUB_APP_SLUG,
        commit_message="feat: add report",
        commit_author_name=COMMIT_AUTHOR,
        commit_author_email=COMMIT_AUTHOR_EMAIL,
        commit_timestamp=COMMIT_TIMESTAMP,
        title="feat: add report",
        body="Creates one report.",
        operations=(NormalizedTreeOperation(path="README.md", mode="100644", content=b"hello"),),
    )


def _draft_pr(
    *,
    repository: str = REPOSITORY,
    base_branch: str = "main",
    base_sha: str = BASE_SHA,
    branch: str = BRANCH,
    head_sha: str = COMMIT_SHA,
    draft: bool = True,
    state: str = "open",
    creator_login: str | None = CREATOR_LOGIN,
    github_app_slug: str | None = GITHUB_APP_SLUG,
    title: str = "feat: add report",
    body: str = "Creates one report.",
) -> dict[str, object]:
    return {
        "number": 42,
        "html_url": "https://github.com/posthog/posthog/pull/42",
        "draft": draft,
        "state": state,
        "title": title,
        "body": body,
        "user": {"login": creator_login} if creator_login is not None else None,
        "performed_via_github_app": {"slug": github_app_slug} if github_app_slug is not None else None,
        "base": {"ref": base_branch, "sha": base_sha, "repo": {"full_name": repository}},
        "head": {"ref": branch, "sha": head_sha, "repo": {"full_name": repository}},
    }


def _commit_responses() -> dict[tuple[str, str], list[_Response | Exception]]:
    return {
        ("GET", f"/repos/{REPOSITORY}/git/ref/heads/main"): [
            _Response(200, {"object": {"sha": BASE_SHA}}),
            _Response(200, {"object": {"sha": BASE_SHA}}),
            _Response(200, {"object": {"sha": BASE_SHA}}),
            _Response(200, {"object": {"sha": BASE_SHA}}),
            _Response(200, {"object": {"sha": BASE_SHA}}),
        ],
        ("GET", f"/repos/{REPOSITORY}/git/commits/{BASE_SHA}"): [
            _Response(200, {"sha": BASE_SHA, "tree": {"sha": "b" * 40}})
        ],
        ("POST", f"/repos/{REPOSITORY}/git/blobs"): [_Response(201, {"sha": _blob_sha(b"hello")})],
        ("POST", f"/repos/{REPOSITORY}/git/trees"): [_Response(201, {"sha": "e" * 40})],
        ("POST", f"/repos/{REPOSITORY}/git/commits"): [_Response(201, {"sha": COMMIT_SHA})],
        ("GET", f"/repos/{REPOSITORY}/git/commits/{COMMIT_SHA}"): [
            _Response(
                200,
                {
                    "sha": COMMIT_SHA,
                    "message": "feat: add report",
                    "tree": {"sha": "e" * 40},
                    "parents": [{"sha": BASE_SHA}],
                    "author": {"name": COMMIT_AUTHOR, "email": COMMIT_AUTHOR_EMAIL, "date": "1970-01-01T00:16:40Z"},
                    "committer": {"name": COMMIT_AUTHOR, "email": COMMIT_AUTHOR_EMAIL, "date": "1970-01-01T00:16:40Z"},
                },
            )
        ],
    }


@pytest.mark.parametrize("operation", ["commit", "pull"])
def test_moved_base_branch_blocks_new_mutations(operation: str) -> None:
    call: Callable[[], object]
    if operation == "commit":
        responses = _commit_responses()
        responses[("GET", f"/repos/{REPOSITORY}/git/ref/heads/main")] = [_Response(200, {"object": {"sha": "f" * 40}})]
        fake = _GitHubFake(responses)
        call = lambda: create_server_commit(fake, _publication())
    else:
        fake = _GitHubFake(
            {("GET", f"/repos/{REPOSITORY}/git/ref/heads/main"): [_Response(200, {"object": {"sha": "f" * 40}})]}
        )
        call = lambda: create_draft_pull_request(fake, _publication(), COMMIT_SHA)

    with pytest.raises(PublicationConflictError):
        call()

    assert all(method == "GET" for method, _path, _kwargs in fake.requests)


@pytest.mark.parametrize(
    ("base_tips", "expected_post_paths"),
    [
        (
            [BASE_SHA, "f" * 40],
            [f"/repos/{REPOSITORY}/git/blobs"],
        ),
        (
            [BASE_SHA, BASE_SHA, "f" * 40],
            [f"/repos/{REPOSITORY}/git/blobs", f"/repos/{REPOSITORY}/git/trees"],
        ),
    ],
)
def test_moved_base_after_a_git_object_blocks_each_later_mutation(
    base_tips: list[str], expected_post_paths: list[str]
) -> None:
    responses = _commit_responses()
    responses[("GET", f"/repos/{REPOSITORY}/git/ref/heads/main")] = [
        _Response(200, {"object": {"sha": base_tip}}) for base_tip in base_tips
    ]
    fake = _GitHubFake(responses)

    with pytest.raises(PublicationConflictError):
        create_server_commit(fake, _publication())

    assert [path for method, path, _kwargs in fake.requests if method == "POST"] == expected_post_paths


def test_server_commit_rejects_a_base_response_for_a_different_commit() -> None:
    responses = _commit_responses()
    responses[("GET", f"/repos/{REPOSITORY}/git/commits/{BASE_SHA}")] = [
        _Response(200, {"sha": "f" * 40, "tree": {"sha": "b" * 40}})
    ]

    with pytest.raises(PublicationConflictError):
        create_server_commit(_GitHubFake(responses), _publication())


def test_server_commit_rejects_a_blob_response_that_does_not_match_its_content() -> None:
    responses = _commit_responses()
    responses[("POST", f"/repos/{REPOSITORY}/git/blobs")] = [_Response(201, {"sha": "d" * 40})]

    with pytest.raises(PublicationConflictError):
        create_server_commit(_GitHubFake(responses), _publication())


@pytest.mark.parametrize(
    "verified_commit",
    [
        {"sha": "f" * 40, "message": "feat: add report", "tree": {"sha": "e" * 40}, "parents": [{"sha": BASE_SHA}]},
        {"sha": COMMIT_SHA, "message": "different", "tree": {"sha": "e" * 40}, "parents": [{"sha": BASE_SHA}]},
    ],
)
def test_server_commit_rejects_a_verification_response_with_wrong_identity_or_message(
    verified_commit: dict[str, object],
) -> None:
    responses = _commit_responses()
    responses[("GET", f"/repos/{REPOSITORY}/git/commits/{COMMIT_SHA}")] = [_Response(200, verified_commit)]

    with pytest.raises(PublicationConflictError):
        create_server_commit(_GitHubFake(responses), _publication())


@pytest.mark.parametrize(
    "base_branch",
    [
        " leading",
        "trailing ",
        "bad~ref",
        "bad^ref",
        "bad:ref",
        "bad?ref",
        "bad*ref",
        "bad[ref",
        "bad@{ref",
        "/bad",
        "bad/",
        ".bad",
        "bad.",
        "bad..ref",
        "bad//ref",
        "bad.lock",
        "bad.lock/ref",
    ],
)
def test_transport_rejects_unsafe_base_branches_before_any_publication(base_branch: str) -> None:
    publication = DraftPublicationInput(
        repository=REPOSITORY,
        base_sha=BASE_SHA,
        base_branch=base_branch,
        branch=BRANCH,
        expected_creator_login=CREATOR_LOGIN,
        expected_github_app_slug=GITHUB_APP_SLUG,
        commit_message="feat: add report",
        commit_author_name=COMMIT_AUTHOR,
        commit_author_email=COMMIT_AUTHOR_EMAIL,
        commit_timestamp=COMMIT_TIMESTAMP,
        title="feat: add report",
        body="Creates one report.",
        operations=(NormalizedTreeOperation(path="README.md", mode="100644", content=b"hello"),),
    )
    fake = _GitHubFake(
        {("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"): [_Response(200, {"object": {"sha": COMMIT_SHA}})]}
    )

    with pytest.raises(ValueError):
        create_server_branch(fake, publication, COMMIT_SHA)

    assert fake.requests == []


def test_publish_sequence_creates_one_parent_server_commit_then_verified_draft() -> None:
    responses = _commit_responses()
    responses.update(
        {
            ("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"): [_Response(404, {})],
            ("POST", f"/repos/{REPOSITORY}/git/refs"): [
                _Response(201, {"ref": f"refs/heads/{BRANCH}", "object": {"sha": COMMIT_SHA}})
            ],
            ("POST", f"/repos/{REPOSITORY}/pulls"): [_Response(201, _draft_pr())],
        }
    )
    fake = _GitHubFake(responses)

    commit_sha = create_server_commit(fake, _publication())
    branch = create_server_branch(fake, _publication(), commit_sha)
    pull_request = create_draft_pull_request(fake, _publication(), commit_sha)

    assert commit_sha == COMMIT_SHA
    assert branch is BranchCreation.CREATED
    assert pull_request.pr_number == 42
    assert fake.requests[-1] == (
        "POST",
        f"/repos/{REPOSITORY}/pulls",
        {
            "endpoint": "/repos/{owner}/{repo}/pulls",
            "params": None,
            "json_body": {
                "title": "feat: add report",
                "body": "Creates one report.",
                "head": BRANCH,
                "base": "main",
                "draft": True,
            },
            "priority": Priority.CRITICAL,
            "retry_transient": False,
        },
    )


def test_server_commit_preserves_allowed_executable_mode_and_explicit_deletion() -> None:
    publication = DraftPublicationInput(
        repository=REPOSITORY,
        base_sha=BASE_SHA,
        base_branch="main",
        branch=BRANCH,
        expected_creator_login=CREATOR_LOGIN,
        expected_github_app_slug=GITHUB_APP_SLUG,
        commit_message="feat: update scripts",
        commit_author_name=COMMIT_AUTHOR,
        commit_author_email=COMMIT_AUTHOR_EMAIL,
        commit_timestamp=COMMIT_TIMESTAMP,
        title="feat: update scripts",
        body="Updates scripts.",
        operations=(
            NormalizedTreeOperation(path="bin/check", mode="100755", content=b"#!/bin/sh\ntrue\n"),
            NormalizedTreeOperation(path="obsolete.py", mode="100644", content=None),
        ),
    )
    responses = _commit_responses()
    responses[("POST", f"/repos/{REPOSITORY}/git/blobs")] = [_Response(201, {"sha": _blob_sha(b"#!/bin/sh\ntrue\n")})]
    responses[("GET", f"/repos/{REPOSITORY}/git/commits/{COMMIT_SHA}")] = [
        _Response(
            200,
            {
                "sha": COMMIT_SHA,
                "message": "feat: update scripts",
                "tree": {"sha": "e" * 40},
                "parents": [{"sha": BASE_SHA}],
                "author": {"name": COMMIT_AUTHOR, "email": COMMIT_AUTHOR_EMAIL, "date": "1970-01-01T00:16:40Z"},
                "committer": {"name": COMMIT_AUTHOR, "email": COMMIT_AUTHOR_EMAIL, "date": "1970-01-01T00:16:40Z"},
            },
        )
    ]
    fake = _GitHubFake(responses)

    create_server_commit(fake, publication)

    tree_request = next(request for request in fake.requests if request[1].endswith("/git/trees"))
    assert tree_request[2]["json_body"] == {
        "base_tree": "b" * 40,
        "tree": [
            {"path": "bin/check", "mode": "100755", "type": "blob", "sha": _blob_sha(b"#!/bin/sh\ntrue\n")},
            {"path": "obsolete.py", "mode": "100644", "type": "blob", "sha": None},
        ],
    }
    commit_request = next(request for request in fake.requests if request[1].endswith("/git/commits"))
    assert commit_request[2]["json_body"] == {
        "message": "feat: update scripts",
        "tree": "e" * 40,
        "parents": [BASE_SHA],
        "author": {"name": COMMIT_AUTHOR, "email": COMMIT_AUTHOR_EMAIL, "date": "1970-01-01T00:16:40Z"},
        "committer": {"name": COMMIT_AUTHOR, "email": COMMIT_AUTHOR_EMAIL, "date": "1970-01-01T00:16:40Z"},
    }


def test_existing_exact_server_branch_returns_existing_without_pr_create() -> None:
    fake = _GitHubFake(
        {("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"): [_Response(200, {"object": {"sha": COMMIT_SHA}})]}
    )

    result = create_server_branch(fake, _publication(), COMMIT_SHA)

    assert result is BranchCreation.EXISTS_EXACT
    assert all(method == "GET" for method, _path, _kwargs in fake.requests)


@pytest.mark.parametrize(
    "payload",
    [
        _draft_pr(repository="other/repository"),
        _draft_pr(base_branch="trunk"),
        _draft_pr(base_sha="not-a-sha"),
        _draft_pr(branch="codex/ffffffffffffffffffffffffffffffff"),
        _draft_pr(head_sha="f" * 40),
        _draft_pr(draft=False),
        _draft_pr(creator_login="other-app[bot]"),
        _draft_pr(creator_login=None),
        _draft_pr(github_app_slug="other-app"),
        _draft_pr(title="Unreviewed title"),
        _draft_pr(body="Unreviewed body"),
    ],
)
def test_reconciliation_rejects_unverified_pull_request_bindings(payload: dict[str, object]) -> None:
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"): [_Response(200, {"object": {"sha": COMMIT_SHA}})],
            ("GET", f"/repos/{REPOSITORY}/pulls"): [_Response(200, [payload])],
        }
    )

    with pytest.raises((PublicationConflictError, ClosedPublicationError)):
        reconcile_draft_pull_request(fake, _publication(), expected_branch_sha=COMMIT_SHA)


def test_reconciliation_accepts_the_intended_base_branch_after_its_tip_advances() -> None:
    advanced_base = "f" * 40
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"): [_Response(200, {"object": {"sha": COMMIT_SHA}})],
            ("GET", f"/repos/{REPOSITORY}/pulls"): [_Response(200, [_draft_pr(base_sha=advanced_base)])],
            ("GET", f"/repos/{REPOSITORY}/compare/{BASE_SHA}...{advanced_base}"): [
                _Response(
                    200,
                    {
                        "status": "ahead",
                        "ahead_by": 1,
                        "behind_by": 0,
                        "base_commit": {"sha": BASE_SHA},
                        "merge_base_commit": {"sha": BASE_SHA},
                    },
                )
            ],
        }
    )

    result = reconcile_draft_pull_request(fake, _publication(), expected_branch_sha=COMMIT_SHA)

    assert result is not None
    assert result.pr_number == 42


def test_reconciliation_rejects_a_rewritten_base_branch() -> None:
    rewritten_base = "f" * 40
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"): [_Response(200, {"object": {"sha": COMMIT_SHA}})],
            ("GET", f"/repos/{REPOSITORY}/pulls"): [_Response(200, [_draft_pr(base_sha=rewritten_base)])],
            ("GET", f"/repos/{REPOSITORY}/compare/{BASE_SHA}...{rewritten_base}"): [
                _Response(
                    200,
                    {
                        "status": "diverged",
                        "ahead_by": 1,
                        "behind_by": 1,
                        "base_commit": {"sha": BASE_SHA},
                        "merge_base_commit": {"sha": "e" * 40},
                    },
                )
            ],
        }
    )

    with pytest.raises(PublicationConflictError, match="no longer descends"):
        reconcile_draft_pull_request(fake, _publication(), expected_branch_sha=COMMIT_SHA)


def test_reconciliation_blocks_a_closed_pull_request_without_recreating_it() -> None:
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"): [_Response(200, {"object": {"sha": COMMIT_SHA}})],
            ("GET", f"/repos/{REPOSITORY}/pulls"): [_Response(200, [_draft_pr(state="closed")])],
        }
    )

    with pytest.raises(ClosedPublicationError):
        reconcile_draft_pull_request(fake, _publication(), expected_branch_sha=COMMIT_SHA)

    assert all(method == "GET" for method, _path, _kwargs in fake.requests)


def test_ref_422_returns_exact_existing_branch_without_a_second_create() -> None:
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"): [
                _Response(404, {}),
                _Response(200, {"object": {"sha": COMMIT_SHA}}),
            ],
            ("GET", f"/repos/{REPOSITORY}/git/ref/heads/main"): [_Response(200, {"object": {"sha": BASE_SHA}})],
            ("POST", f"/repos/{REPOSITORY}/git/refs"): [_Response(422, {})],
        }
    )

    result = create_server_branch(fake, _publication(), COMMIT_SHA)

    assert result is BranchCreation.EXISTS_EXACT
    assert [path for method, path, _kwargs in fake.requests if method == "POST"] == [f"/repos/{REPOSITORY}/git/refs"]


def test_pull_request_422_reconciles_without_a_second_create() -> None:
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/ref/heads/main"): [_Response(200, {"object": {"sha": BASE_SHA}})],
            ("POST", f"/repos/{REPOSITORY}/pulls"): [_Response(422, {})],
            ("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"): [_Response(200, {"object": {"sha": COMMIT_SHA}})],
            ("GET", f"/repos/{REPOSITORY}/pulls"): [_Response(200, [_draft_pr()])],
        }
    )

    result = create_draft_pull_request(fake, _publication(), COMMIT_SHA)

    assert result.pr_number == 42
    assert [path for method, path, _kwargs in fake.requests if method == "POST"] == [f"/repos/{REPOSITORY}/pulls"]


def test_rate_limit_is_propagated_without_transport_retry() -> None:
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/ref/heads/main"): [_Response(200, {"object": {"sha": BASE_SHA}})],
            ("GET", f"/repos/{REPOSITORY}/git/commits/{BASE_SHA}"): [GitHubRateLimitError("limited", retry_after=60)],
        }
    )

    with pytest.raises(GitHubRateLimitError):
        create_server_commit(fake, _publication())

    assert len(fake.requests) == 1


@pytest.mark.parametrize("operation", ["ref", "pull"])
def test_mutation_timeout_is_ambiguous_and_never_retried(operation: str) -> None:
    responses = _commit_responses()
    if operation == "ref":
        responses.update(
            {
                ("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"): [_Response(404, {})],
                ("POST", f"/repos/{REPOSITORY}/git/refs"): [TimeoutError("connection dropped")],
            }
        )
    else:
        responses.update({("POST", f"/repos/{REPOSITORY}/pulls"): [TimeoutError("connection dropped")]})
    fake = _GitHubFake(responses)

    with pytest.raises(PublicationAmbiguousError):
        if operation == "ref":
            create_server_branch(fake, _publication(), COMMIT_SHA)
        else:
            create_draft_pull_request(fake, _publication(), COMMIT_SHA)

    expected_path = f"/repos/{REPOSITORY}/git/refs" if operation == "ref" else f"/repos/{REPOSITORY}/pulls"
    assert [path for method, path, _kwargs in fake.requests if method == "POST" and path == expected_path] == [
        expected_path
    ]


@pytest.mark.parametrize("operation", ["ref", "pull"])
def test_mutation_http_408_is_ambiguous_and_never_retried(operation: str) -> None:
    call: Callable[[], object]
    if operation == "ref":
        fake = _GitHubFake(
            {
                ("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"): [_Response(404, {})],
                ("GET", f"/repos/{REPOSITORY}/git/ref/heads/main"): [_Response(200, {"object": {"sha": BASE_SHA}})],
                ("POST", f"/repos/{REPOSITORY}/git/refs"): [_Response(408, {})],
            }
        )
        call = lambda: create_server_branch(fake, _publication(), COMMIT_SHA)
        expected_path = f"/repos/{REPOSITORY}/git/refs"
    else:
        fake = _GitHubFake(
            {
                ("GET", f"/repos/{REPOSITORY}/git/ref/heads/main"): [_Response(200, {"object": {"sha": BASE_SHA}})],
                ("POST", f"/repos/{REPOSITORY}/pulls"): [_Response(408, {})],
            }
        )
        call = lambda: create_draft_pull_request(fake, _publication(), COMMIT_SHA)
        expected_path = f"/repos/{REPOSITORY}/pulls"

    with pytest.raises(PublicationAmbiguousError):
        call()

    assert [path for method, path, _kwargs in fake.requests if method == "POST"] == [expected_path]


def test_ambiguous_reconciliation_uses_zero_create_requests() -> None:
    fake = _GitHubFake(
        {
            ("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}"): [_Response(200, {"object": {"sha": COMMIT_SHA}})],
            ("GET", f"/repos/{REPOSITORY}/pulls"): [_Response(200, [_draft_pr()])],
        }
    )

    result = reconcile_draft_pull_request(fake, _publication(), expected_branch_sha=COMMIT_SHA)

    assert result is not None
    assert result.pr_number == 42
    assert all(method == "GET" for method, _path, _kwargs in fake.requests)
