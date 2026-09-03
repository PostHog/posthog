import time
from typing import Any

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.egress.github.transport import GitHubRateLimitError

from products.review_hog.backend.reviewer.artefact_content import ThreadVerdictArtefact
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError
from products.review_hog.backend.reviewer.tools.github_threads import (
    REVIEW_HOG_FINDING_MARKER,
    ReviewThread,
    ThreadAction,
    ThreadComment,
    classify_thread,
    fetch_unresolved_threads,
    github_graphql_request,
    inspect_fix_commit,
    is_restricted_fix_path,
    order_threads,
    should_resolve,
)

_THREADS = "products.review_hog.backend.reviewer.tools.github_threads"


def _thread(
    thread_id: str = "PRRT_1",
    *,
    author_login: str = "alice",
    author_is_bot: bool = False,
    created_at: str = "2026-07-01T00:00:00Z",
    comment_ids: list[int | None] | None = None,
    first_body: str = "please fix",
) -> ReviewThread:
    ids = comment_ids if comment_ids is not None else [100]
    comments = [
        ThreadComment(
            id=comment_id,
            author_login=author_login if index == 0 else "someone",
            author_is_bot=author_is_bot if index == 0 else False,
            body=first_body if index == 0 else "a reply",
            created_at=created_at,
        )
        for index, comment_id in enumerate(ids)
    ]
    return ReviewThread(thread_id=thread_id, path="f.py", line=10, comments=comments)


def _verdict(
    thread_id: str = "PRRT_1",
    *,
    outcome: str = "wont_fix",
    author_is_bot: bool = False,
    latest_comment_id: int | None = 100,
    reply_posted: bool = True,
    resolved: bool = False,
    commit_verified: bool | None = None,
    commit_restricted: bool | None = None,
) -> ThreadVerdictArtefact:
    return ThreadVerdictArtefact(
        thread_id=thread_id,
        outcome=outcome,
        author_is_bot=author_is_bot,
        reasoning="checked",
        reply="answered",
        latest_comment_id=latest_comment_id,
        reply_posted=reply_posted,
        resolved=resolved,
        commit_verified=commit_verified,
        commit_restricted=commit_restricted,
    )


def _commit_payload(
    *, files: list[dict[str, Any]] | None = None, author: dict[str, Any] | None = None, verified: bool = True
) -> dict[str, Any]:
    return {
        "files": files or [],
        "author": author if author is not None else {"login": "posthog[bot]", "type": "Bot"},
        "commit": {"verification": {"verified": verified}},
    }


class TestGitHubThreads:
    @parameterized.expand(
        [
            # (name, verdict kwargs or None, thread comment ids, expected action)
            ("no_verdict_needs_triage", None, [100], ThreadAction.TRIAGE),
            # A newer comment than the watermark re-opens triage (pushback on a WON'T FIX).
            ("new_comment_reopens_triage", {"latest_comment_id": 100}, [100, 250], ThreadAction.TRIAGE),
            # Judged but the reply never landed: redo the GitHub writes only.
            ("unposted_reply_redelivers", {"reply_posted": False}, [100], ThreadAction.SIDE_EFFECTS),
            # Bot thread on a terminal outcome whose resolve failed: redeliver the resolve.
            (
                "bot_unresolved_terminal_redelivers",
                {"author_is_bot": True, "outcome": "fixed", "resolved": False},
                [100],
                ThreadAction.SIDE_EFFECTS,
            ),
            # Human thread fully delivered: never resolved by design, so nothing left to do.
            ("human_delivered_skips", {"author_is_bot": False}, [100], ThreadAction.SKIP),
            # Escalations never resolve, so a delivered escalation on a bot thread is done too.
            (
                "bot_escalate_delivered_skips",
                {"author_is_bot": True, "outcome": "escalate"},
                [100],
                ThreadAction.SKIP,
            ),
            (
                "bot_resolved_skips",
                {"author_is_bot": True, "outcome": "fixed", "resolved": True},
                [100],
                ThreadAction.SKIP,
            ),
            # An unproven fix claim never resolves, so the delivered verdict settles as SKIP —
            # not a perpetual SIDE_EFFECTS redelivery loop.
            (
                "bot_fixed_unverified_delivered_skips",
                {"author_is_bot": True, "outcome": "fixed", "commit_verified": False, "resolved": False},
                [100],
                ThreadAction.SKIP,
            ),
            # Same settling for the hard-floor backstop: a restricted fix stays open for a human.
            (
                "bot_fixed_restricted_delivered_skips",
                {
                    "author_is_bot": True,
                    "outcome": "fixed",
                    "commit_verified": True,
                    "commit_restricted": True,
                    "resolved": False,
                },
                [100],
                ThreadAction.SKIP,
            ),
        ]
    )
    def test_classify_thread(self, _name: str, verdict_kwargs: dict | None, comment_ids: list, expected: str) -> None:
        verdict = _verdict(**verdict_kwargs) if verdict_kwargs is not None else None
        assert classify_thread(_thread(comment_ids=comment_ids), verdict) == expected

    @parameterized.expand(
        [
            ("human_terminal_never", False, "fixed", False, None),
            ("bot_fixed_resolves", True, "fixed", True, None),
            ("bot_wont_fix_resolves", True, "wont_fix", True, None),
            ("bot_escalate_never", True, "escalate", False, None),
            ("bot_fixed_verified_resolves", True, "fixed", True, True),
            ("bot_fixed_unverified_never", True, "fixed", False, False),
        ]
    )
    def test_should_resolve_etiquette(
        self, _name: str, author_is_bot: bool, outcome: str, expected: bool, commit_verified: bool | None
    ) -> None:
        verdict = _verdict(author_is_bot=author_is_bot, outcome=outcome, commit_verified=commit_verified)
        assert should_resolve(verdict) is expected

    def test_should_resolve_restricted_fixed_never(self) -> None:
        verdict = _verdict(author_is_bot=True, outcome="fixed", commit_verified=True, commit_restricted=True)
        assert should_resolve(verdict) is False

    @parameterized.expand(
        [
            ("workflows", ".github/workflows/ci.yml", True),
            ("anything_under_dot_github", ".github/dependabot.yml", True),
            ("codeowners_anywhere", "docs/CODEOWNERS", True),
            ("lockfile", "products/foo/pnpm-lock.yaml", True),
            ("manifest", "package.json", True),
            ("normal_source_file", "products/foo/backend/api.py", False),
            ("name_containing_lookalike", "src/package.json.md", False),
        ]
    )
    def test_is_restricted_fix_path(self, _name: str, path: str, expected: bool) -> None:
        assert is_restricted_fix_path(path) is expected

    @parameterized.expand(
        [
            ("modified_restricted", {"filename": ".github/workflows/ci.yml"}, [".github/workflows/ci.yml"]),
            # A rename out of a restricted location is one entry whose new name looks clean; the old
            # name must still flag, or relocating a workflow file bypasses the backstop entirely.
            (
                "renamed_out_of_restricted",
                {"filename": "scripts/ci.bak", "previous_filename": ".github/workflows/ci.yml"},
                [".github/workflows/ci.yml"],
            ),
            ("clean", {"filename": "products/foo/backend/api.py"}, []),
        ]
    )
    def test_inspect_fix_commit_restricted_paths(
        self, _name: str, file_entry: dict[str, Any], expected: list[str]
    ) -> None:
        response = Mock()
        response.json.return_value = _commit_payload(files=[file_entry])
        with patch(f"{_THREADS}.github_api_request", return_value=response):
            inspection = inspect_fix_commit(token="t", owner="o", repo="r", sha="abc")
        assert inspection.restricted_paths == expected
        assert inspection.provenance_ok is True

    @parameterized.expand(
        [
            # A reachable ancestor authored by a human must not pass as the run's own fix commit.
            ("human_author", {"login": "alice", "type": "User"}, True),
            ("unsigned_commit", {"login": "posthog[bot]", "type": "Bot"}, False),
        ]
    )
    def test_inspect_fix_commit_rejects_bad_provenance(
        self, _name: str, author: dict[str, Any], verified: bool
    ) -> None:
        response = Mock()
        response.json.return_value = _commit_payload(author=author, verified=verified)
        with patch(f"{_THREADS}.github_api_request", return_value=response):
            assert inspect_fix_commit(token="t", owner="o", repo="r", sha="abc").provenance_ok is False

    def test_order_threads_ranks_humans_then_reviewhog_then_other_bots_oldest_first(self) -> None:
        other_bot = _thread(
            "PRRT_bot", author_login="greptile[bot]", author_is_bot=True, created_at="2026-07-01T00:00:00Z"
        )
        review_hog = _thread(
            "PRRT_rh",
            author_login="posthog-app[bot]",
            author_is_bot=True,
            created_at="2026-07-02T00:00:00Z",
            # Recognized by the marker ReviewHog stamps on its comments, not the login (deployment-varying).
            first_body=f"### A finding\n\n{REVIEW_HOG_FINDING_MARKER}",
        )
        human_new = _thread("PRRT_h2", author_login="bob", created_at="2026-07-03T00:00:00Z")
        human_old = _thread("PRRT_h1", author_login="alice", created_at="2026-07-01T00:00:00Z")

        ordered = order_threads([other_bot, review_hog, human_new, human_old])
        assert [t.thread_id for t in ordered] == ["PRRT_h1", "PRRT_h2", "PRRT_rh", "PRRT_bot"]

    def test_latest_comment_id_ignores_ghost_comments(self) -> None:
        assert _thread(comment_ids=[100, None, 250]).latest_comment_id == 250
        assert _thread(comment_ids=[None]).latest_comment_id is None


def _graphql_page(nodes: list[dict[str, Any]], *, has_next: bool = False, cursor: str | None = None) -> dict[str, Any]:
    return {
        "repository": {
            "pullRequest": {
                "reviewThreads": {
                    "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                    "nodes": nodes,
                }
            }
        }
    }


def _node(
    thread_id: str,
    *,
    resolved: bool = False,
    typename: str = "User",
    line: int | None = 12,
    original_line: int | None = None,
) -> dict[str, Any]:
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": True,
        "path": "f.py",
        "line": line,
        "originalLine": original_line,
        "comments": {
            "nodes": [
                {
                    "databaseId": 7,
                    "url": "https://github.com/o/r/pull/1#discussion_r7",
                    "body": "hm",
                    "createdAt": "2026-07-01T00:00:00Z",
                    "authorAssociation": "MEMBER",
                    "author": {"login": "alice", "__typename": typename},
                }
            ]
        },
    }


class TestFetchUnresolvedThreads:
    def test_filters_resolved_and_parses_bot_flag_across_pages(self) -> None:
        pages = [
            _graphql_page([_node("PRRT_1"), _node("PRRT_resolved", resolved=True)], has_next=True, cursor="c1"),
            _graphql_page([_node("PRRT_2", typename="Bot")]),
        ]
        with patch(f"{_THREADS}.github_graphql_request", side_effect=pages) as request:
            threads = fetch_unresolved_threads(token="t", owner="o", repo="r", pr_number=1)

        assert [t.thread_id for t in threads] == ["PRRT_1", "PRRT_2"]
        assert threads[0].is_outdated is True
        assert threads[0].author_is_bot is False
        assert threads[0].comments[0].author_association == "MEMBER"
        assert threads[1].author_is_bot is True
        # The second page must be requested with the first page's cursor.
        assert request.call_args_list[1].args[1]["cursor"] == "c1"

    def test_pages_comment_tail_when_inner_connection_overflows(self) -> None:
        # A >50-comment thread's newest activity lives past the first page; without the tail the
        # watermark freezes below the real latest comment and the thread never re-opens to triage.
        overflowing = _node("PRRT_long")
        overflowing["comments"]["pageInfo"] = {"hasNextPage": True, "endCursor": "tail-c1"}
        tail_page = {
            "node": {
                "comments": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "databaseId": 900,
                            "url": "",
                            "body": "late pushback",
                            "createdAt": "2026-07-02T00:00:00Z",
                            "authorAssociation": "MEMBER",
                            "author": {"login": "bob", "__typename": "User"},
                        }
                    ],
                }
            }
        }
        pages = [_graphql_page([overflowing]), tail_page]
        with patch(f"{_THREADS}.github_graphql_request", side_effect=pages) as request:
            threads = fetch_unresolved_threads(token="t", owner="o", repo="r", pr_number=1)

        assert threads[0].latest_comment_id == 900
        tail_variables = request.call_args_list[1].args[1]
        assert tail_variables["id"] == "PRRT_long"
        assert tail_variables["cursor"] == "tail-c1"

    def test_outdated_thread_falls_back_to_original_line(self) -> None:
        # GitHub nulls `line` once the thread's code drifts; without the originalLine fallback every
        # outdated thread loses its anchor in the resolution prompt.
        pages = [_graphql_page([_node("PRRT_out", line=None, original_line=42), _node("PRRT_cur")])]
        with patch(f"{_THREADS}.github_graphql_request", side_effect=pages):
            threads = fetch_unresolved_threads(token="t", owner="o", repo="r", pr_number=1)

        assert threads[0].line == 42
        assert threads[1].line == 12


class TestGithubGraphqlRequest:
    def test_raises_on_graphql_errors_despite_http_200(self) -> None:
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"data": None, "errors": [{"message": "Resource not accessible"}]}
        with patch(f"{_THREADS}.github_request", return_value=response):
            with pytest.raises(GitHubAPIError, match="Resource not accessible"):
                github_graphql_request("query {}", {}, token="t")

    def test_raises_rate_limit_error_on_200_rate_limited_graphql_error(self) -> None:
        # GraphQL's primary rate limit is a 200 + errors[].type RATE_LIMITED — it must surface as
        # GitHubRateLimitError (the codebase's distinct rate-limit signal), not a generic API error.
        reset = int(time.time()) + 120
        response = Mock(ok=True, status_code=200)
        response.headers = {"x-ratelimit-reset": str(reset)}
        response.json.return_value = {
            "data": None,
            "errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded for installation ID 1."}],
        }
        with patch(f"{_THREADS}.github_request", return_value=response):
            with pytest.raises(GitHubRateLimitError) as exc_info:
                github_graphql_request("query {}", {}, token="t")
        assert exc_info.value.reset_at == reset
        assert exc_info.value.retry_after is not None and exc_info.value.retry_after >= 1

    def test_returns_data_payload(self) -> None:
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"data": {"x": 1}}
        with patch(f"{_THREADS}.github_request", return_value=response):
            assert github_graphql_request("query {}", {}, token="t") == {"x": 1}
