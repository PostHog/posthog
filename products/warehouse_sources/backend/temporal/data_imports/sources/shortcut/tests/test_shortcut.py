import json
import random
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.settings import SHORTCUT_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.shortcut import (
    SHORTCUT_BASE_URL,
    STORY_SEARCH_EPOCH_START,
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
    def test_non_list_response_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"unexpected": "shape"})])

        # A 200 body that isn't the expected bare array means the API shape changed — fail loud
        # rather than syncing the stray object as a single row.
        with pytest.raises(ValueError, match="list response body"):
            _rows(shortcut_source("token", "epics", 1, "j"))


class TestRetryAndErrorClassification:
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


class TestShortcutSourceShape:
    def test_stories_is_the_only_incremental_endpoint(self) -> None:
        # Sanity check that mirrors the schema-level contract in the settings catalog.
        incremental = {name for name, cfg in SHORTCUT_ENDPOINTS.items() if cfg.incremental_params}
        assert incremental == {"stories"}
