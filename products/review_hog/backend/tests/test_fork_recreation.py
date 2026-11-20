import re
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.review_hog.backend.fork_recreation import ForkRecreation, latest_approvals

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
        self.reviews = reviews
        self.permissions = permissions
        self.files = files
        self.changed_on_base = changed_on_base
        self.trees = {
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
        if method == "POST":
            self.writes.append((path.removeprefix(base), json_body))
            return _Response(201, {"sha": f"sha-{len(self.writes)}", "number": 12, "html_url": "https://pr/12"})
        routes: dict[str, _Response] = {
            f"{base}/pulls/7": _Response(
                200,
                {
                    "state": "open",
                    "title": "Fix the widget",
                    "body": "It was broken",
                    "user": {"login": "jane"},
                    "head": {"sha": LATER_SHA, "repo": {"full_name": "jane/widgets"}},
                    "base": {"ref": "main", "repo": {"default_branch": "main"}},
                },
            ),
            f"{base}/git/ref/heads/fork-pr/7": _Response(200 if self.branch_exists else 404),
            f"{base}/pulls?head=acme:fork-pr/7&state=open": _Response(
                200, [{"number": 12, "html_url": "https://pr/12"}] if self.branch_exists else []
            ),
            f"{base}/git/ref/heads/main": _Response(200, {"object": {"sha": BASE_SHA}}),
            f"{base}/git/commits/{BASE_SHA}": _Response(200, {"tree": {"sha": BASE_TREE_SHA}}),
            f"{base}/compare/{BASE_SHA}...{APPROVED_SHA}": _Response(
                200,
                {
                    "merge_base_commit": {"sha": MERGE_BASE_SHA},
                    "files": self.files,
                    "commits": [
                        {
                            "parents": [{}],
                            "author": {"login": "jane"},
                            "commit": {"author": {"name": "Jane", "email": "jane@example.com"}},
                        },
                        {
                            "parents": [{}],
                            "author": {"login": "sam"},
                            "commit": {"author": {"name": "Sam", "email": "sam@example.com"}},
                        },
                        {
                            "parents": [{}, {}],
                            "author": {"login": "merger"},
                            "commit": {"author": {"name": "Merger", "email": "merger@example.com"}},
                        },
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

    def get_collaborator_permission(self, repository: str, username: str) -> str:
        return self.permissions.get(username, "none")

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


def _review(login: str, user_id: int, state: str, commit_id: str = APPROVED_SHA) -> dict[str, Any]:
    return {"user": {"login": login, "id": user_id}, "state": state, "commit_id": commit_id}


FILES = [
    {"filename": "src/app.py", "status": "modified"},
    {"filename": "tools/run.sh", "status": "added"},
    {"filename": "old.txt", "status": "removed"},
    {"filename": "docs/b.md", "status": "renamed", "previous_filename": "docs/a.md"},
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
            "Co-authored-by: Jane <42+jane@users.noreply.github.com>\nCo-authored-by: Sam <sam@example.com>"
        )
        assert writes["/git/refs"] == {"ref": "refs/heads/fork-pr/7", "sha": "sha-2"}
        assert writes["/pulls"]["head"] == "fork-pr/7" and writes["/pulls"]["base"] == "main"
        assert "<!-- fork-pr: 7 @jane -->" in writes["/pulls"]["body"]
        assert github.labels == expected_labels
        assert github.reviewers == ["alice"]
        assert "#12" in github.comments[0] and "not included" in github.comments[0]
        assert github.closed == [7]

    @parameterized.expand(
        [
            (
                "conflict_with_the_default_branch",
                [_review("alice", 1, "APPROVED")],
                {"alice": "write"},
                FILES,
                frozenset({"src/app.py"}),
                "also changed on the default branch",
            ),
            (
                "approval_without_write_access",
                [_review("alice", 1, "APPROVED")],
                {"alice": "read"},
                FILES,
                frozenset(),
                "No one with write access has approved",
            ),
            (
                "approval_withdrawn",
                [_review("alice", 1, "APPROVED"), _review("alice", 1, "CHANGES_REQUESTED", commit_id=LATER_SHA)],
                {"alice": "write"},
                FILES,
                frozenset(),
                "No one with write access has approved",
            ),
            *[
                (
                    f"ci_file_{path}",
                    [_review("alice", 1, "APPROVED")],
                    {"alice": "write"},
                    [*FILES, {"filename": path, "status": "modified"}],
                    frozenset(),
                    "changes files CI runs",
                )
                for path in [
                    ".github/workflows/ci.yml",
                    ".depot/workflows/ci-backend.yml",
                    "frontend/package.json",
                    "bin/start",
                    "posthog/conftest.py",
                    "docker/Dockerfile.dev",
                ]
            ],
        ]
    )
    def test_refuses_without_writing_anything(
        self,
        _name: str,
        reviews: list[dict[str, Any]],
        permissions: dict[str, str],
        files: list[dict[str, Any]],
        changed_on_base: frozenset[str],
        expected: str,
    ) -> None:
        github = FakeGitHub(reviews=reviews, permissions=permissions, files=files, changed_on_base=changed_on_base)

        with self.assertRaisesRegex(Exception, expected):
            ForkRecreation(github, REPOSITORY, 7).run()  # type: ignore[arg-type]

        assert github.writes == [] and github.comments == [] and github.closed == []

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
