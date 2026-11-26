import random
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests.exceptions import HTTPError

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.shortcut._config import ShortcutSourceConfig
from products.warehouse_sources.sources.shortcut.settings import SHORTCUT_ENDPOINTS
from products.warehouse_sources.sources.shortcut.shortcut import (
    SHORTCUT_BASE_URL,
    STORY_SEARCH_EPOCH_START,
    _build_search_body,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.sources.shortcut.source import ShortcutSource


def _driver(token: str = "secret-token") -> SourceDriver:
    return SourceDriver(ShortcutSource(), ShortcutSourceConfig(api_token=token))


def _story(story_id: int, created_at: str) -> dict[str, Any]:
    return {"id": story_id, "created_at": created_at}


def _stories_search_fake(
    stories: list[dict[str, Any]], cap: int | None = None, order: str = "asc", exclusive_bounds: bool = False
) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer `POST /stories/search` the way the live endpoint might.

    Filters on the created_at window in the body (inclusive bounds unless ``exclusive_bounds``),
    returns rows in ``order`` (``asc``, ``desc``, or ``shuffled``), and cuts the response at ``cap``
    rows without saying so.
    """

    def respond(request: RecordedRequest) -> ScriptedResponse:
        body = request.json()
        start, end = body["created_at_start"], body["created_at_end"]
        if exclusive_bounds:
            rows = [s for s in stories if start < s["created_at"] < end]
        else:
            rows = [s for s in stories if start <= s["created_at"] <= end]
        rows.sort(key=lambda s: s["created_at"], reverse=order == "desc")
        if order == "shuffled":
            random.Random(len(rows)).shuffle(rows)
        return ScriptedResponse(json=rows if cap is None else rows[:cap])

    return respond


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04T00:00:00Z", "2026-03-04T00:00:00Z"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        result = _format_incremental_value(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildSearchBody:
    @pytest.mark.parametrize(
        "incremental_field, expected",
        [
            # A created_at cursor overrides the epoch floor; an updated_at cursor rides alongside it.
            # Every story search asks for the description via includes_description.
            ("created_at", {"created_at_start": "2026-01-02T03:04:05Z", "includes_description": True}),
            (
                "updated_at",
                {
                    "updated_at_start": "2026-01-02T03:04:05Z",
                    "created_at_start": STORY_SEARCH_EPOCH_START,
                    "includes_description": True,
                },
            ),
            (
                None,
                {
                    "updated_at_start": "2026-01-02T03:04:05Z",
                    "created_at_start": STORY_SEARCH_EPOCH_START,
                    "includes_description": True,
                },
            ),
        ],
    )
    def test_maps_field_to_server_side_filter(self, incremental_field: str | None, expected: dict) -> None:
        body = _build_search_body(
            SHORTCUT_ENDPOINTS["stories"], True, datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), incremental_field
        )
        assert body == expected

    def test_non_search_endpoint_has_no_body(self) -> None:
        # GET list endpoints carry no request body at all.
        body = _build_search_body(SHORTCUT_ENDPOINTS["members"], True, datetime(2026, 1, 1, tzinfo=UTC), "updated_at")
        assert body == {}


class TestRequests:
    @pytest.mark.parametrize(
        "endpoint, path, body, expected",
        [
            (
                "epic_workflow",
                "/epic-workflow",
                {"id": 1, "epic_states": [{"id": 20, "name": "Started"}], "default_epic_state_id": 20},
                [{"id": 1, "epic_states": [{"id": 20, "name": "Started"}], "default_epic_state_id": 20}],
            ),
            (
                "documents",
                "/documents",
                [
                    {
                        "id": "00000000-0000-4000-8000-000000000001",
                        "title": "Example plan",
                        "app_url": "https://example.com/doc",
                    }
                ],
                [
                    {
                        "id": "00000000-0000-4000-8000-000000000001",
                        "title": "Example plan",
                        "app_url": "https://example.com/doc",
                    }
                ],
            ),
            ("documents", "/documents", [], []),
        ],
    )
    def test_additional_top_level_shapes(
        self, endpoint: str, path: str, body: Any, expected: list[dict[str, Any]]
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.rows == expected
        assert result.paths == [f"/api/v3{path}"]
        assert result.requests[0].method == "GET"

    @pytest.mark.parametrize("parent_ids", [[], [1, 2, 3]])
    def test_epic_comments_retains_parent_ids_and_threaded_replies(self, parent_ids: list[int]) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            path = request.path
            if path == "/api/v3/epics":
                return ScriptedResponse(json=[{"id": parent_id} for parent_id in parent_ids])
            epic_id = int(path.split("/")[-2])
            assert path == f"/api/v3/epics/{epic_id}/comments"
            return ScriptedResponse(
                json=[] if epic_id == 2 else [{"id": 10, "text": "Example comment", "comments": [{"id": 11}]}]
            )

        result = _driver().run("epic_comments", respond)

        assert result.raised is None
        assert result.rows == [
            {"epic_id": epic_id, "id": 10, "text": "Example comment", "comments": [{"id": 11}]}
            for epic_id in parent_ids
            if epic_id != 2
        ]
        assert result.paths == ["/api/v3/epics", *[f"/api/v3/epics/{epic_id}/comments" for epic_id in parent_ids]]
        assert all(not request.query for request in result.requests)

    def test_story_history_reads_all_parents_once_across_search_windows(self) -> None:
        stories = [_story(i, f"2025-0{i}-01T00:00:00Z") for i in range(1, 5)]
        search = _stories_search_fake(stories, cap=2, order="desc")

        def respond(request: RecordedRequest) -> ScriptedResponse:
            path = request.path
            if path == "/api/v3/stories/search":
                assert request.method == "POST"
                assert request.json()["created_at_start"]
                assert request.json()["includes_description"] is True
                return search(request)
            story_id = int(path.split("/")[-2])
            assert path == f"/api/v3/stories/{story_id}/history"
            assert request.method == "GET"
            assert request.json() is None
            return ScriptedResponse(
                json=[{"id": "change-1", "changed_at": "2025-05-01T00:00:00Z", "actions": [{"action": "update"}]}]
            )

        result = _driver().run("story_history", respond)

        assert result.raised is None
        assert sorted(result.rows, key=lambda row: row["story_id"]) == [
            {
                "story_id": i,
                "id": "change-1",
                "changed_at": "2025-05-01T00:00:00Z",
                "actions": [{"action": "update"}],
            }
            for i in range(1, 5)
        ]
        history_paths = [path for path in result.paths if path.endswith("/history")]
        assert sorted(history_paths) == [f"/api/v3/stories/{i}/history" for i in range(1, 5)]

    def test_auth_uses_shortcut_token_header_and_content_headers(self) -> None:
        result = _driver().run("members", [ScriptedResponse(json=[{"id": 1}])])

        headers = result.requests[0].headers
        assert headers["shortcut-token"] == "secret-token"
        # Non-secret content headers ride on the session, not the redacted auth.
        assert headers["accept"] == "application/json"
        assert headers["content-type"] == "application/json"

    @pytest.mark.parametrize(
        "cap, order, exclusive_bounds, split_threshold",
        [
            # No cap: the first window is complete and only gets confirmed.
            (None, "asc", False, 1000),
            # A cap below the split threshold, newest first: the paginator must notice the
            # truncation itself, and the order of rows must not matter.
            (3, "desc", False, 1000),
            (3, "shuffled", False, 1000),
            # The same cap with bounds the endpoint treats as exclusive: the window overlap must
            # keep the stories on the midpoint seconds.
            (3, "desc", True, 1000),
            # A cap at the split threshold: every full response is split straight away.
            (2, "asc", False, 2),
        ],
    )
    def test_stories_reads_every_story_whatever_the_cap_and_order(
        self, cap: int | None, order: str, exclusive_bounds: bool, split_threshold: int
    ) -> None:
        stories = [
            _story(i, f"2025-{month:02d}-{day:02d}T0{day}:00:00Z")
            for i, (month, day) in enumerate(
                [(1, 1), (1, 1), (2, 3), (5, 7), (5, 7), (6, 8), (9, 1), (9, 2), (11, 4), (12, 9)], start=1
            )
        ]

        with mock.patch(
            "products.warehouse_sources.sources.shortcut.shortcut.STORY_SEARCH_SPLIT_THRESHOLD",
            split_threshold,
        ):
            result = _driver().run(
                "stories", _stories_search_fake(stories, cap=cap, order=order, exclusive_bounds=exclusive_bounds)
            )

        # Every story lands exactly once, whatever the endpoint held back or how it ordered rows.
        assert result.raised is None
        assert sorted(row["id"] for row in result.rows) == list(range(1, 11))

    def test_non_list_response_fails_loud(self) -> None:
        # A 200 body that isn't the expected bare array means the API shape changed — fail loud
        # rather than syncing the stray object as a single row.
        result = _driver().run("epics", [ScriptedResponse(json={"unexpected": "shape"})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestRetryAndErrorClassification:
    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_client_errors_raise_without_retry(self, status_code: int) -> None:
        result = _driver().run("members", [ScriptedResponse(status=status_code, json={"error": "nope"})])

        assert isinstance(result.raised, HTTPError)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, message_substr",
        [
            (418, False, "unexpected status: 418"),
        ],
    )
    def test_status_mapping(self, status_code, expected_valid, message_substr) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, error = validate_credentials("token")

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert message_substr in (error or "")
        assert network.requests_log[0].url == f"{SHORTCUT_BASE_URL}/member"


class TestShortcutSourceShape:
    def test_stories_is_the_only_incremental_endpoint(self) -> None:
        # Sanity check that mirrors the schema-level contract in the settings catalog.
        incremental = {name for name, cfg in SHORTCUT_ENDPOINTS.items() if cfg.incremental_params}
        assert incremental == {"stories"}
