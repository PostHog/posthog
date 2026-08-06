from typing import Any

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from products.review_hog.backend.reviewer.artefact_content import ThreadVerdictArtefact
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError
from products.review_hog.backend.reviewer.tools.github_threads import (
    ReviewThread,
    ThreadAction,
    ThreadComment,
    classify_thread,
    fetch_unresolved_threads,
    github_graphql_request,
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
    )


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
        ]
    )
    def test_classify_thread(self, _name: str, verdict_kwargs: dict | None, comment_ids: list, expected: str) -> None:
        verdict = _verdict(**verdict_kwargs) if verdict_kwargs is not None else None
        assert classify_thread(_thread(comment_ids=comment_ids), verdict) == expected

    @parameterized.expand(
        [
            ("human_terminal_never", False, "fixed", False),
            ("bot_fixed_resolves", True, "fixed", True),
            ("bot_wont_fix_resolves", True, "wont_fix", True),
            ("bot_escalate_never", True, "escalate", False),
        ]
    )
    def test_should_resolve_etiquette(self, _name: str, author_is_bot: bool, outcome: str, expected: bool) -> None:
        assert should_resolve(_verdict(author_is_bot=author_is_bot, outcome=outcome)) is expected

    def test_order_threads_ranks_humans_then_reviewhog_then_other_bots_oldest_first(self) -> None:
        other_bot = _thread(
            "PRRT_bot", author_login="greptile[bot]", author_is_bot=True, created_at="2026-07-01T00:00:00Z"
        )
        review_hog = _thread(
            "PRRT_rh",
            author_login="posthog-app[bot]",
            author_is_bot=True,
            created_at="2026-07-02T00:00:00Z",
            first_body="**ReviewHog** found an issue",
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


def _node(thread_id: str, *, resolved: bool = False, typename: str = "User") -> dict[str, Any]:
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": True,
        "path": "f.py",
        "line": 12,
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


class TestGithubGraphqlRequest:
    def test_raises_on_graphql_errors_despite_http_200(self) -> None:
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"data": None, "errors": [{"message": "Resource not accessible"}]}
        with patch(f"{_THREADS}.github_request", return_value=response):
            with pytest.raises(GitHubAPIError, match="Resource not accessible"):
                github_graphql_request("query {}", {}, token="t")

    def test_returns_data_payload(self) -> None:
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"data": {"x": 1}}
        with patch(f"{_THREADS}.github_request", return_value=response):
            assert github_graphql_request("query {}", {}, token="t") == {"x": 1}
