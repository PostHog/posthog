from collections.abc import Callable
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.bluesky import (
    BlueskyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.source import PRIMARY_KEYS, BlueskySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bluesky import (
    BlueskySourceConfig,
)


class TestValidateCredentials:
    @pytest.mark.parametrize("actor", ["jay.bsky.team", "@jay.bsky.team", " jay.bsky.team "])
    def test_valid_actor(self, actor: str) -> None:
        with scripted_network([ScriptedResponse(json={"did": "did:plc:abc"})]) as network:
            is_valid, message = validate_credentials(actor)

        assert (is_valid, message) == (True, None)
        assert len(network.requests_log) == 1
        assert network.requests_log[0].url == (
            "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=jay.bsky.team"
        )
        assert network.requests_log[0].method == "GET"

    @pytest.mark.parametrize(
        "response",
        [
            ScriptedResponse(status=400, body=b"<html>not json</html>"),
            ScriptedResponse(
                status=400,
                json={"error": "InvalidRequest", "message": "Invalid app.bsky.actor.getProfile params: bad actor"},
            ),
        ],
    )
    def test_bad_actor_returns_actionable_message(self, response: ScriptedResponse) -> None:
        with scripted_network([response]):
            is_valid, message = validate_credentials("missing.bsky.social")

        assert is_valid is False
        assert message == "That handle or DID couldn't be found on Bluesky. Check the spelling and try again."

    def test_unexpected_status_falls_back_to_generic_message(self) -> None:
        with scripted_network(always(ScriptedResponse(status=503, json={}))):
            is_valid, message = validate_credentials("jay.bsky.team")

        assert is_valid is False
        assert message == "Bluesky returned an unexpected error (503)."


class TestBlueskySourceResumeBehavior:
    """Run Bluesky resume behavior through the source pipeline."""

    @staticmethod
    def _driver(actor: str = "jay.bsky.team") -> SourceDriver:
        return SourceDriver(BlueskySource(), BlueskySourceConfig(actor=actor))

    @pytest.mark.parametrize(
        ("endpoint", "list_key", "item"),
        [
            ("Posts", "feed", {"post": {"uri": "at://x"}}),
            ("Followers", "followers", {"did": "did:plc:1"}),
            ("Follows", "follows", {"did": "did:plc:1"}),
        ],
    )
    def test_fresh_run_saves_cursor_after_each_non_terminal_page(
        self, endpoint: str, list_key: str, item: dict[str, Any]
    ) -> None:
        result = self._driver().run(
            endpoint,
            [
                ScriptedResponse(json={list_key: [item], "cursor": "cursor-1"}),
                ScriptedResponse(json={list_key: [item], "cursor": "cursor-2"}),
                ScriptedResponse(json={list_key: [item]}),
            ],
        )

        assert result.raised is None
        assert result.params("cursor") == [None, "cursor-1", "cursor-2"]
        assert result.saved_states == [
            BlueskyResumeConfig(cursor="cursor-1"),
            BlueskyResumeConfig(cursor="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._driver().run(
            "Followers",
            [ScriptedResponse(json={"followers": [{"did": "did:plc:1"}]})],
            resume_state=BlueskyResumeConfig(cursor="cursor-resumed"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["cursor-resumed"]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = self._driver().run("Followers", [ScriptedResponse(json={"followers": [{"did": "did:plc:1"}]})])

        assert result.raised is None
        assert result.params("cursor") == [None]

    def test_profile_endpoint_is_a_single_page_and_never_saves_state(self) -> None:
        result = self._driver("@jay.bsky.team").run(
            "Profile", [ScriptedResponse(json={"did": "did:plc:1", "handle": "jay.bsky.team"})]
        )

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.params("actor") == ["jay.bsky.team"]
        assert result.saved_states == []

    def test_posts_yields_flattened_post_objects(self) -> None:
        result = self._driver().run(
            "Posts",
            [ScriptedResponse(json={"feed": [{"post": {"uri": "at://x", "indexedAt": "2026-01-01T00:00:00Z"}}]})],
        )

        assert result.raised is None
        assert result.items == [[{"uri": "at://x", "indexedAt": "2026-01-01T00:00:00Z"}]]


POST_1 = "at://did:plc:abc/app.bsky.feed.post/1"
# A did:web AT-URI can carry a percent-encoded port, which must reach the API unchanged.
POST_2 = "at://did:web:example.com%3A8080/app.bsky.feed.post/2"


def _post_fanout_script(
    list_key: str, child_row: Callable[[int], dict[str, Any]]
) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("getAuthorFeed"):
            if request.param("cursor") is None:
                return ScriptedResponse(json={"feed": [{"post": {"uri": POST_1}}], "cursor": "feed-2"})
            return ScriptedResponse(json={"feed": [{"post": {"uri": POST_2}}]})
        if request.param("cursor") is None:
            body: dict[str, Any] = {list_key: [child_row(1)]}
            if request.param("uri") == POST_1:
                body["cursor"] = "child-2"
            return ScriptedResponse(json=body)
        return ScriptedResponse(json={list_key: [child_row(2)]})

    return respond


POST_FANOUT_CASES = [
    (
        "Likes",
        "likes",
        lambda n: {"actor": {"did": f"did:plc:liker{n}"}, "indexedAt": "2026-01-01T00:00:00Z"},
        [(POST_1, "did:plc:liker1"), (POST_1, "did:plc:liker2"), (POST_2, "did:plc:liker1")],
    ),
    (
        "Quotes",
        "posts",
        lambda n: {"uri": f"at://did:plc:quoter/app.bsky.feed.post/{n}", "indexedAt": "2026-01-01T00:00:00Z"},
        [
            (POST_1, "at://did:plc:quoter/app.bsky.feed.post/1"),
            (POST_1, "at://did:plc:quoter/app.bsky.feed.post/2"),
            (POST_2, "at://did:plc:quoter/app.bsky.feed.post/1"),
        ],
    ),
]


class TestBlueskyPostFanout:
    @staticmethod
    def _driver(actor: str = "jay.bsky.team") -> SourceDriver:
        return SourceDriver(BlueskySource(), BlueskySourceConfig(actor=actor))

    @pytest.mark.parametrize(("endpoint", "list_key", "child_row", "expected_keys"), POST_FANOUT_CASES)
    def test_walks_every_post_and_child_page(
        self,
        endpoint: str,
        list_key: str,
        child_row: Callable[[int], dict[str, Any]],
        expected_keys: list[tuple[str, str]],
    ) -> None:
        result = self._driver().run(endpoint, _post_fanout_script(list_key, child_row))

        assert result.raised is None
        assert [tuple(row[key] for key in PRIMARY_KEYS[endpoint]) for row in result.rows] == expected_keys
        child_requests = [r for r in result.requests if not r.path.endswith("getAuthorFeed")]
        assert [(r.param("uri"), r.param("cursor")) for r in child_requests] == [
            (POST_1, None),
            (POST_1, "child-2"),
            (POST_2, None),
        ]

    @pytest.mark.parametrize(("endpoint", "list_key", "child_row", "expected_keys"), POST_FANOUT_CASES)
    @pytest.mark.parametrize(
        ("resume_state", "expected_child_requests", "expected_rows"),
        [
            (
                BlueskyResumeConfig(post_uri=POST_1, child_cursor="child-2"),
                [(POST_1, "child-2"), (POST_2, None)],
                slice(1, None),
            ),
            (BlueskyResumeConfig(feed_cursor="feed-2"), [(POST_2, None)], slice(2, None)),
        ],
    )
    def test_resume_continues_from_saved_position(
        self,
        endpoint: str,
        list_key: str,
        child_row: Callable[[int], dict[str, Any]],
        expected_keys: list[tuple[str, str]],
        resume_state: BlueskyResumeConfig,
        expected_child_requests: list[tuple[str, str | None]],
        expected_rows: slice,
    ) -> None:
        result = self._driver().run(endpoint, _post_fanout_script(list_key, child_row), resume_state=resume_state)

        assert result.raised is None
        child_requests = [r for r in result.requests if not r.path.endswith("getAuthorFeed")]
        assert [(r.param("uri"), r.param("cursor")) for r in child_requests] == expected_child_requests
        assert [tuple(row[key] for key in PRIMARY_KEYS[endpoint]) for row in result.rows] == expected_keys[
            expected_rows
        ]

    @pytest.mark.parametrize(("endpoint", "list_key", "child_row", "expected_keys"), POST_FANOUT_CASES)
    def test_saves_fixed_size_position_before_each_child_page(
        self,
        endpoint: str,
        list_key: str,
        child_row: Callable[[int], dict[str, Any]],
        expected_keys: list[tuple[str, str]],
    ) -> None:
        result = self._driver().run(endpoint, _post_fanout_script(list_key, child_row))

        assert result.saved_states == [
            BlueskyResumeConfig(post_uri=POST_1, child_cursor="child-2"),
            BlueskyResumeConfig(feed_cursor="feed-2"),
        ]
