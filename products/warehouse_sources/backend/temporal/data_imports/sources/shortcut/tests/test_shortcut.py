import json
import random
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Request, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.settings import (
    ENDPOINTS,
    SHORTCUT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.shortcut import (
    SHORTCUT_BASE_URL,
    STORY_SEARCH_EPOCH_START,
    StoriesSearchPaginator,
    _build_search_body,
    _format_incremental_value,
    shortcut_source,
    validate_credentials,
)

# RESTClient builds its request session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the shortcut module.
SHORTCUT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.shortcut.make_tracked_session"
)
# Neutralize tenacity's backoff sleeps so the retry path runs instantly.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _wire(
    session: mock.MagicMock, responses: list[Response] | Callable[[dict[str, Any]], Response]
) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's method/url/json/auth AT SEND TIME.

    The framework builds a single ``Request`` and mutates it in place across pages, so inspecting it
    after the run shows only the final state — snapshot a copy when each request is prepared instead.
    ``responses`` is either a list consumed in order, or a callable answering each request snapshot.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(
            {
                "method": request.method,
                "url": request.url,
                "json": dict(request.json) if isinstance(request.json, dict) else request.json,
                "params": dict(request.params or {}),
                "auth": request.auth,
            }
        )
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    if callable(responses):
        respond = responses
        session.send.side_effect = lambda *args, **kwargs: respond(snapshots[-1])
    else:
        session.send.side_effect = responses
    return snapshots


def _story(story_id: int, created_at: str) -> dict[str, Any]:
    return {"id": story_id, "created_at": created_at}


def _stories_search_fake(
    stories: list[dict[str, Any]], cap: int | None = None, order: str = "asc", exclusive_bounds: bool = False
) -> Callable[[dict[str, Any]], Response]:
    """Answer `POST /stories/search` the way the live endpoint might.

    Filters on the created_at window in the body (inclusive bounds unless ``exclusive_bounds``),
    returns rows in ``order`` (``asc``, ``desc``, or ``shuffled``), and cuts the response at ``cap``
    rows without saying so.
    """

    def respond(snapshot: dict[str, Any]) -> Response:
        body = snapshot["json"]
        start, end = body["created_at_start"], body["created_at_end"]
        if exclusive_bounds:
            rows = [s for s in stories if start < s["created_at"] < end]
        else:
            rows = [s for s in stories if start <= s["created_at"] <= end]
        rows.sort(key=lambda s: s["created_at"], reverse=order == "desc")
        if order == "shuffled":
            random.Random(len(rows)).shuffle(rows)
        return _response(rows if cap is None else rows[:cap])

    return respond


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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
    def test_full_refresh_sends_created_at_floor(self) -> None:
        # An empty body returns zero stories, so full refresh must still carry the epoch floor.
        # includes_description asks the endpoint for the description column the schema advertises.
        body = _build_search_body(SHORTCUT_ENDPOINTS["stories"], False, None, None)
        assert body == {"created_at_start": STORY_SEARCH_EPOCH_START, "includes_description": True}

    def test_first_incremental_run_sends_created_at_floor(self) -> None:
        body = _build_search_body(SHORTCUT_ENDPOINTS["stories"], True, None, "updated_at")
        assert body == {"created_at_start": STORY_SEARCH_EPOCH_START, "includes_description": True}

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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_get_endpoint_yields_full_list_in_one_request(self, MockSession) -> None:
        session = MockSession.return_value
        rows = [{"id": 1}, {"id": 2}]
        snaps = _wire(session, [_response(rows)])

        result = _rows(shortcut_source("token", "members", 1, "j"))

        assert result == rows
        assert session.send.call_count == 1
        assert snaps[0]["method"] == "GET"
        assert snaps[0]["url"] == f"{SHORTCUT_BASE_URL}/members"
        # A flat GET carries no request body.
        assert snaps[0]["json"] is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_uses_shortcut_token_header_and_content_headers(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": 1}])])

        _rows(shortcut_source("secret-token", "members", 1, "j"))

        auth = snaps[0]["auth"]
        assert auth.name == "Shortcut-Token"
        assert auth.location == "header"
        assert auth.api_key == "secret-token"
        # Non-secret content headers ride on the session, not the redacted auth.
        assert session.headers.get("Accept") == "application/json"
        assert session.headers.get("Content-Type") == "application/json"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stories_uses_post_with_incremental_body(self, MockSession) -> None:
        session = MockSession.return_value
        story = _story(10, "2026-01-03T00:00:00Z")
        snaps = _wire(session, _stories_search_fake([story]))

        result = _rows(
            shortcut_source(
                "token",
                "stories",
                1,
                "j",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        assert result == [story]
        assert snaps[0]["method"] == "POST"
        assert snaps[0]["url"] == f"{SHORTCUT_BASE_URL}/stories/search"
        # The server-side timestamp filter rides in the POST body, not the query string. The
        # paginator closes the first created_at window at the moment the sync started.
        body = snaps[0]["json"]
        assert body["updated_at_start"] == "2026-01-02T03:04:05Z"
        assert body["created_at_start"] == STORY_SEARCH_EPOCH_START
        assert body["includes_description"] is True
        assert datetime.strptime(body["created_at_end"], "%Y-%m-%dT%H:%M:%SZ") > datetime(2026, 1, 3)
        assert snaps[0]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stories_full_refresh_sends_non_empty_body(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, _stories_search_fake([_story(10, "2026-01-03T00:00:00Z")]))

        _rows(shortcut_source("token", "stories", 1, "j"))

        assert snaps[0]["method"] == "POST"
        # The outgoing body is never empty — an empty body returns zero stories.
        assert snaps[0]["json"]["created_at_start"] == STORY_SEARCH_EPOCH_START
        assert snaps[0]["json"]["includes_description"] is True

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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stories_reads_every_story_whatever_the_cap_and_order(
        self, MockSession, cap: int | None, order: str, exclusive_bounds: bool, split_threshold: int
    ) -> None:
        session = MockSession.return_value
        stories = [
            _story(i, f"2025-{month:02d}-{day:02d}T0{day}:00:00Z")
            for i, (month, day) in enumerate(
                [(1, 1), (1, 1), (2, 3), (5, 7), (5, 7), (6, 8), (9, 1), (9, 2), (11, 4), (12, 9)], start=1
            )
        ]
        _wire(session, _stories_search_fake(stories, cap=cap, order=order, exclusive_bounds=exclusive_bounds))

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.shortcut.STORY_SEARCH_SPLIT_THRESHOLD",
            split_threshold,
        ):
            rows = _rows(shortcut_source("token", "stories", 1, "j"))

        # Every story lands exactly once, whatever the endpoint held back or how it ordered rows.
        assert sorted(row["id"] for row in rows) == list(range(1, 11))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stories_past_the_cap_in_one_second_stop_with_a_warning(self, MockSession, caplog) -> None:
        session = MockSession.return_value
        # Three stories share one created_at second and the endpoint returns two at most, so no
        # window can separate them. The sync must keep what it can get and say so, not loop.
        stories = [_story(i, "2025-03-04T05:06:07Z") for i in range(1, 4)]
        _wire(session, _stories_search_fake(stories, cap=2))

        with caplog.at_level("WARNING"):
            rows = _rows(shortcut_source("token", "stories", 1, "j"))

        assert len({row["id"] for row in rows}) == 2
        assert "cannot be split" in caplog.text
        # Splitting from the epoch down to one second takes tens of requests, not thousands.
        assert session.send.call_count < 200

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_list_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(shortcut_source("token", "epics", 1, "j")) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_response_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"unexpected": "shape"})])

        # A 200 body that isn't the expected bare array means the API shape changed — fail loud
        # rather than syncing the stray object as a single row.
        with pytest.raises(ValueError, match="list response body"):
            _rows(shortcut_source("token", "epics", 1, "j"))


class TestStoriesSearchPaginator:
    def _window(self, request: Request) -> tuple[str, str]:
        return request.json["created_at_start"], request.json["created_at_end"]

    def test_first_window_runs_from_the_floor_to_the_sync_start(self) -> None:
        paginator = StoriesSearchPaginator(now=datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC))
        request = Request(method="POST", url="x", json={"created_at_start": "2026-01-01T00:00:00Z"})

        paginator.init_request(request)

        assert self._window(request) == ("2026-01-01T00:00:00Z", "2026-03-01T12:00:00Z")

    def test_full_response_splits_the_window_at_the_midpoint_second(self) -> None:
        paginator = StoriesSearchPaginator(split_threshold=2, now=datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC))
        request = Request(method="POST", url="x", json={"created_at_start": "2026-01-01T00:00:00Z"})
        paginator.init_request(request)
        rows = [_story(1, "2026-01-01T00:00:00Z"), _story(2, "2026-01-01T00:00:03Z")]

        paginator.update_state(_response(rows), rows)
        assert paginator.has_next_page is True
        paginator.update_request(request)
        first = self._window(request)
        paginator.update_state(_response([]), [])
        paginator.update_request(request)
        second = self._window(request)

        # The halves overlap around the midpoint second; which half is fetched first does not matter.
        assert sorted([first, second]) == [
            ("2026-01-01T00:00:00Z", "2026-01-01T00:00:06Z"),
            ("2026-01-01T00:00:05Z", "2026-01-01T00:00:10Z"),
        ]


class TestRetryAndErrorClassification:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_succeed(self, MockSession, _mock_sleep, status_code: int) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "transient"}, status_code), _response([{"id": 7}])])

        result = _rows(shortcut_source("token", "members", 1, "j"))

        assert result == [{"id": 7}]
        # First attempt hit the retryable status, second attempt succeeded.
        assert session.send.call_count == 2

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_without_retry(self, MockSession, _mock_sleep, status_code: int) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "nope"}, status_code)])

        with pytest.raises(HTTPError):
            _rows(shortcut_source("token", "members", 1, "j"))

        assert session.send.call_count == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, message_substr",
        [
            (200, True, None),
            (401, False, "Invalid Shortcut API token"),
            (403, False, "does not have access"),
            (418, False, "unexpected status: 418"),
        ],
    )
    @mock.patch(SHORTCUT_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected_valid, message_substr) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        is_valid, error = validate_credentials("token")

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert message_substr in (error or "")
        assert mock_session.return_value.get.call_args.args[0] == f"{SHORTCUT_BASE_URL}/member"

    @mock.patch(SHORTCUT_SESSION_PATCH)
    def test_transport_error_is_not_valid(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")

        is_valid, error = validate_credentials("token")

        assert is_valid is False
        assert error is not None


class TestShortcutSourceShape:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        response = shortcut_source("token", endpoint, 1, "j")

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Every endpoint partitions on the stable created_at field.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "month"

    @pytest.mark.parametrize("incremental_field", ["created_at", "updated_at", None])
    def test_stories_sort_mode_is_desc_for_every_cursor(self, incremental_field: str | None) -> None:
        # Windows arrive in no cursor order, so desc defers the watermark to the end of the run and a
        # failed batch can't skip rows. None falls back to the updated_at cursor.
        response = shortcut_source(
            "token", "stories", 1, "j", should_use_incremental_field=True, incremental_field=incremental_field
        )
        assert response.sort_mode == "desc"

    def test_stories_is_the_only_incremental_endpoint(self) -> None:
        # Sanity check that mirrors the schema-level contract in the settings catalog.
        incremental = {name for name, cfg in SHORTCUT_ENDPOINTS.items() if cfg.incremental_params}
        assert incremental == {"stories"}
