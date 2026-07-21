import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.settings import (
    ENDPOINTS,
    SHORTCUT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.shortcut import (
    SHORTCUT_BASE_URL,
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


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's method/url/json/auth AT SEND TIME.

    The framework builds a single ``Request`` and mutates it in place across pages, so inspecting it
    after the run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(
            {
                "method": request.method,
                "url": request.url,
                "json": request.json,
                "params": dict(request.params or {}),
                "auth": request.auth,
            }
        )
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


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
    def test_no_incremental_returns_empty_body(self) -> None:
        body = _build_search_body(SHORTCUT_ENDPOINTS["stories"], False, None, None)
        assert body == {}

    def test_incremental_without_last_value_returns_empty_body(self) -> None:
        body = _build_search_body(SHORTCUT_ENDPOINTS["stories"], True, None, "updated_at")
        assert body == {}

    @pytest.mark.parametrize(
        "incremental_field, expected_param",
        [
            ("updated_at", "updated_at_start"),
            ("created_at", "created_at_start"),
            (None, "updated_at_start"),
        ],
    )
    def test_maps_field_to_server_side_filter(self, incremental_field: str | None, expected_param: str) -> None:
        body = _build_search_body(
            SHORTCUT_ENDPOINTS["stories"], True, datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), incremental_field
        )
        assert body == {expected_param: "2026-01-02T03:04:05Z"}

    def test_full_refresh_endpoint_has_no_filter_params(self) -> None:
        # Flat list endpoints expose no incremental params, so even with a cursor we send nothing.
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
        snaps = _wire(session, [_response([{"id": 10}])])

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

        assert result == [{"id": 10}]
        assert snaps[0]["method"] == "POST"
        assert snaps[0]["url"] == f"{SHORTCUT_BASE_URL}/stories/search"
        # The server-side timestamp filter rides in the POST body, not the query string.
        assert snaps[0]["json"] == {"updated_at_start": "2026-01-02T03:04:05Z"}
        assert snaps[0]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stories_full_refresh_sends_empty_body(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": 10}])])

        _rows(shortcut_source("token", "stories", 1, "j"))

        assert snaps[0]["method"] == "POST"
        assert snaps[0]["json"] == {}

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

    def test_stories_is_the_only_incremental_endpoint(self) -> None:
        # Sanity check that mirrors the schema-level contract in the settings catalog.
        incremental = {name for name, cfg in SHORTCUT_ENDPOINTS.items() if cfg.incremental_params}
        assert incremental == {"stories"}
