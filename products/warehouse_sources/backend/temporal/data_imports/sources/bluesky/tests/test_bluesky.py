from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.bluesky import (
    BlueskyResumeConfig,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.source import BlueskySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bluesky import (
    BlueskySourceConfig,
)


class TestGetResource:
    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(KeyError):
            get_resource("Nope", actor="jay.bsky.team")


class TestValidateCredentials:
    def test_valid_actor(self) -> None:
        with scripted_network([ScriptedResponse(json={"did": "did:plc:abc"})]) as network:
            is_valid, message = validate_credentials("jay.bsky.team")

        assert (is_valid, message) == (True, None)
        assert len(network.requests_log) == 1
        assert network.requests_log[0].url == (
            "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=jay.bsky.team"
        )
        assert network.requests_log[0].method == "GET"

    def test_non_json_error_body_falls_back(self) -> None:
        with scripted_network([ScriptedResponse(status=400, body=b"<html>not json</html>")]):
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
    def _driver() -> SourceDriver:
        return SourceDriver(BlueskySource(), BlueskySourceConfig(actor="jay.bsky.team"))

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
        result = self._driver().run("Profile", [ScriptedResponse(json={"did": "did:plc:1", "handle": "jay.bsky.team"})])

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_posts_yields_flattened_post_objects(self) -> None:
        result = self._driver().run(
            "Posts",
            [ScriptedResponse(json={"feed": [{"post": {"uri": "at://x", "indexedAt": "2026-01-01T00:00:00Z"}}]})],
        )

        assert result.raised is None
        assert result.items == [[{"uri": "at://x", "indexedAt": "2026-01-01T00:00:00Z"}]]
