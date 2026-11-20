import re
from collections.abc import Callable
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration import GitHubIntegrationError

from products.review_hog.backend.fork_recreation import (
    ForkRecreation,
    RecreationFailed,
    RecreationRefused,
    latest_approvals,
)

REPOSITORY = "acme/widgets"
BASE_SHA = "b" * 40
BASE_TREE_SHA = "t" * 40
MERGE_BASE_SHA = "m" * 40
APPROVED_SHA = "a" * 40
LATER_SHA = "c" * 40

_OBJECT_FIELD = re.compile(r'(\w+): object\(expression: "([0-9a-z]+):([^"]*)"\)')


class _Response:
    def __init__(self, status_code: int, body: Any = None) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return self._body


class FakeGitHub:
    def __init__(
        self,
        *,
        reviews: list[dict[str, Any]],
        permissions: dict[str, str],
        files: list[dict[str, Any]],
        changed_on_base: frozenset[str] = frozenset(),
    ) -> None:
        self.branch_exists = False
        self.comment_fails = False
        self.failing_posts: set[str] = set()
        self.deleted: list[str] = []
        self.permission_lookups: list[tuple[str, int | None]] = []
        self.open_pull_requests: list[dict[str, Any]] = [{"number": 12, "html_url": "https://pr/12"}]
        self.pr: dict[str, Any] = {
            "state": "open",
            "title": "Fix the widget for @maintainer",
            "body": "It was broken, cc @maintainer",
            "user": {"login": "jane"},
            "head": {"sha": LATER_SHA, "repo": {"full_name": "jane/widgets"}},
            "base": {"ref": "main", "repo": {"default_branch": "main"}},
        }
        self.reviews = reviews
        self.permissions = permissions
        self.files = files
        self.changed_on_base = changed_on_base
        self.trees = {
            "": [{"name": "README.md", "mode": 0o100644, "oid": "blob-readme", "type": "blob"}],
            "src": [{"name": "app.py", "mode": 0o100644, "oid": "blob-app", "type": "blob"}],
            "tools": [{"name": "run.sh", "mode": 0o100755, "oid": "blob-run", "type": "blob"}],
            "docs": [{"name": "b.md", "mode": 0o100644, "oid": "blob-docs", "type": "blob"}],
            ".github/workflows": [{"name": "ci.yml", "mode": 0o100644, "oid": "blob-ci", "type": "blob"}],
        }
        self.writes: list[tuple[str, dict[str, Any]]] = []
        self.labels: list[str] = []
        self.reviewers: list[str] = []
        self.comments: list[str] = []
        self.closed: list[int] = []

    def api_request(
        self, method: str, path: str, *, endpoint: str | None = None, json_body: Any = None, **_: Any
    ) -> _Response:
        base = f"/repos/{REPOSITORY}"
        if method == "POST" and path == "/graphql":
            return _Response(200, {"data": {"repository": self._graphql(json_body["query"])}})
        if method == "DELETE":
            self.deleted.append(path.removeprefix(base))
            return _Response(204)
        if method == "POST":
            if path.removeprefix(base) in self.failing_posts:
                return _Response(422, {})
            self.writes.append((path.removeprefix(base), json_body))
            return _Response(201, {"sha": f"sha-{len(self.writes)}", "number": 12, "html_url": "https://pr/12"})
        routes: dict[str, _Response] = {
            f"{base}/pulls/7": _Response(200, self.pr),
            f"{base}/git/ref/heads/fork-pr/7": _Response(200 if self.branch_exists else 404),
            f"{base}/pulls?head=acme:fork-pr/7&state=open": _Response(200, self.open_pull_requests),
            f"{base}/git/ref/heads/main": _Response(200, {"object": {"sha": BASE_SHA}}),
            f"{base}/git/commits/{BASE_SHA}": _Response(200, {"tree": {"sha": BASE_TREE_SHA}}),
            f"{base}/compare/{BASE_SHA}...{APPROVED_SHA}": _Response(
                200,
                {
                    "merge_base_commit": {"sha": MERGE_BASE_SHA},
                    "files": self.files,
                    "commits": [
                        {"parents": [{}], "author": {"login": "jane", "id": 42}},
                        {"parents": [{}], "author": {"login": "sam", "id": 7}},
                        {"parents": [{}], "author": {"login": "sam", "id": 7}},
                        {"parents": [{}], "author": None},
                        {"parents": [{}, {}], "author": {"login": "merger", "id": 9}},
                    ],
                },
            ),
            "/users/jane": _Response(200, {"login": "jane", "id": 42, "name": "Jane"}),
            f"{base}/labels/trunk-merge-queue-submit": _Response(200, {}),
        }
        return routes[path]

    def _graphql(self, query: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for alias, sha, path in _OBJECT_FIELD.findall(query):
            if alias.startswith("d"):
                result[alias] = {"entries": self.trees.get(path, [])}
            elif sha == BASE_SHA and path in self.changed_on_base:
                result[alias] = {"oid": f"new-{path}"}
            else:
                result[alias] = {"oid": f"old-{path}"}
        return result

    def get_pull_request_reviews(self, repository: str, pr_number: int) -> list[dict[str, Any]]:
        return self.reviews

    def get_collaborator_permission(
        self, repository: str, username: str, *, expected_user_id: int | None = None
    ) -> str:
        self.permission_lookups.append((username, expected_user_id))
        permission = self.permissions.get(username, "none")
        if permission == "lookup_fails":
            raise GitHubIntegrationError("lookup failed")
        return permission

    def add_pull_request_labels(self, repository: str, pr_number: int, labels: list[str]) -> dict[str, Any]:
        self.labels += labels
        return {"success": True}

    def request_pull_request_reviews(self, repository: str, pr_number: int, reviewers: list[str]) -> dict[str, Any]:
        self.reviewers += reviewers
        return {"success": True}

    def has_pull_request_comment(self, repository: str, pr_number: int, marker: str) -> bool:
        return any(marker in comment for comment in self.comments)

    def comment_on_pull_request(self, repository: str, pr_number: int, body: str) -> dict[str, Any]:
        if self.comment_fails:
            return {"success": False}
        self.comments.append(body)
        return {"success": True}

    def close_pull_request(self, repository: str, pr_number: int) -> dict[str, Any]:
        self.closed.append(pr_number)
        return {"success": True}


def _bare_branch(github: FakeGitHub) -> None:
    github.branch_exists = True
    github.open_pull_requests = []


def _review(login: str, user_id: int, state: str, commit_id: str = APPROVED_SHA) -> dict[str, Any]:
    return {"user": {"login": login, "id": user_id}, "state": state, "commit_id": commit_id}


FILES = [
    {"filename": "README.md", "status": "modified"},
    {"filename": "src/app.py", "status": "modified"},
    {"filename": "tools/run.sh", "status": "added"},
    {"filename": "old.txt", "status": "removed"},
    {"filename": "docs/b.md", "status": "renamed", "previous_filename": "docs/a.md"},
]


CI_PATHS = [
    ".github/workflows/ci.yml",
    ".github/CODEOWNERS",
    ".depot/workflows/ci-backend.yml",
    ".GitHub/workflows/ci.yml",
    "frontend/package.json",
    "bin/start",
    "posthog/conftest.py",
    "docker/Dockerfile.dev",
]


class TestForkRecreation(SimpleTestCase):
    def test_the_newest_approval_wins_whoever_reviewed_first(self) -> None:
        reviews = [
            {**_review("alice", 1, "CHANGES_REQUESTED", commit_id="old"), "submitted_at": "2026-11-01T00:00:00Z"},
            {**_review("bob", 2, "APPROVED", commit_id="bob"), "submitted_at": "2026-11-02T00:00:00Z"},
            {**_review("alice", 1, "APPROVED", commit_id="alice"), "submitted_at": "2026-11-03T00:00:00Z"},
        ]

        assert [approval.commit_sha for approval in latest_approvals(reviews)] == ["alice", "bob"]

    @parameterized.expand([("without_enqueue", False, []), ("with_enqueue", True, ["trunk-merge-queue-submit"])])
    def test_squashes_the_approved_commit_onto_the_default_branch(
        self, _name: str, enqueue: bool, expected_labels: list[str]
    ) -> None:
        github = FakeGitHub(
            reviews=[
                _review("alice", 1, "APPROVED"),
                _review("bob", 2, "APPROVED", commit_id=LATER_SHA),
                _review("bob", 2, "COMMENTED", commit_id=LATER_SHA),
            ],
            permissions={"alice": "write"},
            files=FILES,
        )

        outcome = ForkRecreation(github, REPOSITORY, 7, enqueue=enqueue).run()  # type: ignore[arg-type]

        assert outcome.created and outcome.handed_over and outcome.pull_request_number == 12
        writes = dict(github.writes)
        assert writes["/git/trees"] == {
            "base_tree": BASE_TREE_SHA,
            "tree": [
                {"path": "README.md", "mode": "100644", "type": "blob", "sha": "blob-readme"},
                {"path": "src/app.py", "mode": "100644", "type": "blob", "sha": "blob-app"},
                {"path": "tools/run.sh", "mode": "100755", "type": "blob", "sha": "blob-run"},
                {"path": "old.txt", "mode": "100644", "type": "blob", "sha": None},
                {"path": "docs/a.md", "mode": "100644", "type": "blob", "sha": None},
                {"path": "docs/b.md", "mode": "100644", "type": "blob", "sha": "blob-docs"},
            ],
        }
        commit = writes["/git/commits"]
        assert "author" not in commit and commit["parents"] == [BASE_SHA]
        assert commit["message"].endswith(
            "Co-authored-by: Jane <42+jane@users.noreply.github.com>\n"
            "Co-authored-by: sam <7+sam@users.noreply.github.com>"
        )
        assert writes["/git/refs"] == {"ref": "refs/heads/fork-pr/7", "sha": "sha-2"}
        assert writes["/pulls"]["head"] == "fork-pr/7" and writes["/pulls"]["base"] == "main"
        assert "<!-- fork-pr: 7 @jane -->" in writes["/pulls"]["body"]
        assert "cc @\u200bmaintainer" in writes["/pulls"]["body"]
        assert writes["/pulls"]["title"] == "Fix the widget for @\u200bmaintainer"
        assert github.permission_lookups == [("alice", 1)]
        assert github.labels == expected_labels
        assert github.reviewers == ["alice"]
        assert "#12" in github.comments[0] and "not included" in github.comments[0]
        assert github.closed == [7]

    @parameterized.expand(
        [
            ("closed", lambda github: github.pr.update(state="closed"), "closed"),
            (
                "already_in_this_repository",
                lambda github: github.pr["head"].update(repo={"full_name": REPOSITORY}),
                "already on a branch in this repository",
            ),
            ("not_into_the_default_branch", lambda github: github.pr["base"].update(ref="release"), "default branch"),
            ("branch_exists_without_a_pull_request", _bare_branch, "already exists with no open pull request"),
            ("no_changes", lambda github: setattr(github, "files", []), "changes nothing"),
            (
                "too_many_files",
                lambda github: setattr(
                    github, "files", [{"filename": f"f{index}.txt", "status": "added"} for index in range(300)]
                ),
                "300 files or more",
            ),
            (
                "conflict_with_the_default_branch",
                lambda github: setattr(github, "changed_on_base", frozenset({"src/app.py"})),
                "also changed on the default branch",
            ),
            (
                "approval_without_write_access",
                lambda github: github.permissions.update(alice="read"),
                "No one with write access has approved",
            ),
            (
                "approval_withdrawn",
                lambda github: github.reviews.append(_review("alice", 1, "CHANGES_REQUESTED", commit_id=LATER_SHA)),
                "No one with write access has approved",
            ),
            *[
                (
                    f"ci_file_{path}",
                    lambda github, path=path: github.files.append({"filename": path, "status": "modified"}),
                    "changes files CI runs",
                )
                for path in CI_PATHS
            ],
        ]
    )
    def test_refuses_without_writing_anything(
        self, _name: str, configure: Callable[[FakeGitHub], Any], expected: str
    ) -> None:
        github = FakeGitHub(
            reviews=[_review("alice", 1, "APPROVED")], permissions={"alice": "write"}, files=list(FILES)
        )
        configure(github)

        with self.assertRaisesRegex(RecreationRefused, expected):
            ForkRecreation(github, REPOSITORY, 7).run()  # type: ignore[arg-type]

        assert github.writes == [] and github.comments == [] and github.closed == []

    def test_skips_an_approver_whose_permission_lookup_fails(self) -> None:
        github = FakeGitHub(
            reviews=[
                {**_review("alice", 1, "APPROVED"), "submitted_at": "2026-11-01T00:00:00Z"},
                {**_review("ghost", 3, "APPROVED", commit_id=LATER_SHA), "submitted_at": "2026-11-02T00:00:00Z"},
                {**_review("ci[bot]", 4, "APPROVED", commit_id=LATER_SHA), "submitted_at": "2026-11-03T00:00:00Z"},
            ],
            permissions={"alice": "write", "ghost": "lookup_fails"},
            files=list(FILES),
        )

        outcome = ForkRecreation(github, REPOSITORY, 7).run()  # type: ignore[arg-type]

        assert outcome.created and github.reviewers == ["alice"]
        assert github.permission_lookups == [("ghost", 3), ("alice", 1)]

    def test_a_failed_lookup_with_no_verified_approver_fails_rather_than_refuses(self) -> None:
        github = FakeGitHub(
            reviews=[_review("ghost", 3, "APPROVED")], permissions={"ghost": "lookup_fails"}, files=list(FILES)
        )

        with self.assertRaises(RecreationFailed):
            ForkRecreation(github, REPOSITORY, 7).run()  # type: ignore[arg-type]

    def test_deletes_the_branch_when_the_pull_request_cannot_be_opened(self) -> None:
        github = FakeGitHub(
            reviews=[_review("alice", 1, "APPROVED")], permissions={"alice": "write"}, files=list(FILES)
        )
        github.failing_posts = {"/pulls"}

        with self.assertRaises(RecreationFailed):
            ForkRecreation(github, REPOSITORY, 7).run()  # type: ignore[arg-type]

        assert github.deleted == ["/git/refs/heads/fork-pr/7"]
        assert github.comments == [] and github.closed == []

    def test_a_retry_finishes_a_handover_that_failed(self) -> None:
        github = FakeGitHub(reviews=[_review("alice", 1, "APPROVED")], permissions={"alice": "write"}, files=FILES)
        github.comment_fails = True

        first = ForkRecreation(github, REPOSITORY, 7).run()  # type: ignore[arg-type]

        assert first.created and not first.handed_over
        assert github.closed == []

        github.comment_fails = False
        github.branch_exists = True
        writes_before_retry = list(github.writes)

        retry = ForkRecreation(github, REPOSITORY, 7).run()  # type: ignore[arg-type]

        assert retry.handed_over and retry.pull_request_number == 12
        assert github.writes == writes_before_retry
        assert len(github.comments) == 1 and github.closed == [7]
