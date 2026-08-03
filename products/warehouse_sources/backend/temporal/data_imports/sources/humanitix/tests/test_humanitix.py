import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.humanitix import (
    PAGE_SIZE,
    HumanitixResumeConfig,
    humanitix_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.settings import (
    ENDPOINTS,
    HUMANITIX_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the humanitix module.
HUMANITIX_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.humanitix.make_tracked_session"
)
# The client retries 429/5xx behind a real tenacity wait; patch the sleep so the retry path is instant.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _rows(_id_prefix: str, count: int) -> list[dict[str, Any]]:
    return [{"_id": f"{_id_prefix}-{i}"} for i in range(count)]


def _response(
    items: list[dict[str, Any]] | None,
    *,
    total: int | None = None,
    list_key: str = "events",
    drop_key: bool = False,
) -> Response:
    body: dict[str, Any] = {"page": 1, "pageSize": PAGE_SIZE}
    if total is not None:
        body["total"] = total
    if not drop_key:
        body[list_key] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.humanitix.com/v1/events"
    return resp


def _error_response(status: int, reason: str) -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp._content = b"{}"
    resp.url = "https://api.humanitix.com/v1/events?page=1&pageSize=100"
    return resp


def _make_manager(resume_state: HumanitixResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than reading the final state after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _collect(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return humanitix_source(
        api_key="hmtx-key",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_yields_items_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_rows("id", 2), total=2)])

        manager = _make_manager()
        rows = _collect(_source("events", manager))

        assert rows == _rows("id", 2)
        assert params[0] == {"page": 1, "pageSize": PAGE_SIZE}
        assert session.send.call_count == 1
        # A short final page means no further pages, so no resume state is persisted.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_pagination_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(_rows("a", PAGE_SIZE), total=PAGE_SIZE + 1),
                _response(_rows("b", 1), total=PAGE_SIZE + 1),
            ],
        )

        manager = _make_manager()
        rows = _collect(_source("events", manager))

        assert len(rows) == PAGE_SIZE + 1
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        # State is saved AFTER page 1 is yielded (pointing at page 2), and never for the final page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == HumanitixResumeConfig(next_page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_full_page_that_reaches_total(self, MockSession) -> None:
        # A single full page whose length equals total must terminate without fetching page 2.
        session = MockSession.return_value
        _wire(session, [_response(_rows("id", PAGE_SIZE), total=PAGE_SIZE)])

        manager = _make_manager()
        rows = _collect(_source("events", manager))

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        # Page 1 must never be fetched on resume. Total spans 3 pages so page 2 (full) doesn't hit the
        # total-based stop, and page 3 (short) ends the sync.
        params = _wire(
            session,
            [
                _response(_rows("p2", PAGE_SIZE), total=2 * PAGE_SIZE + 1),
                _response(_rows("p3", 1), total=2 * PAGE_SIZE + 1),
            ],
        )

        manager = _make_manager(HumanitixResumeConfig(next_page=2))
        rows = _collect(_source("events", manager))

        assert len(rows) == PAGE_SIZE + 1
        assert params[0]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], total=0)])

        manager = _make_manager()
        rows = _collect(_source("events", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_endpoint_specific_list_key(self, MockSession) -> None:
        # The `tags` endpoint returns its rows under a `tags` key, not `events`.
        session = MockSession.return_value
        _wire(session, [_response(_rows("t", 1), total=1, list_key="tags")])

        manager = _make_manager()
        rows = _collect(_source("tags", manager))

        assert rows == _rows("t", 1)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_list_key_raises_loudly(self, MockSession) -> None:
        # A 200 body without the list key means the response shape changed — fail loud, not 0 rows.
        session = MockSession.return_value
        _wire(session, [_response(None, total=0, drop_key=True)])

        manager = _make_manager()
        with pytest.raises(ValueError, match="matched nothing"):
            _collect(_source("events", manager))


class TestRetryAndErrors:
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        # A 429 raises a retryable error; the retry re-issues the request and the 200 completes it.
        _wire(session, [_error_response(429, "Too Many Requests"), _response(_rows("id", 1), total=1)])

        manager = _make_manager()
        rows = _collect(_source("events", manager))

        assert rows == _rows("id", 1)
        assert session.send.call_count == 2

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_server_error_is_retried(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(500, "Internal Server Error"), _response(_rows("id", 1), total=1)])

        manager = _make_manager()
        rows = _collect(_source("events", manager))

        assert rows == _rows("id", 1)
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_errors_raise_without_retry(self, _name, status, reason, MockSession, _sleep) -> None:
        session = MockSession.return_value
        # A 4xx auth failure is permanent: raise_for_status surfaces an HTTPError and it is not retried.
        _wire(session, [_error_response(status, reason)])

        manager = _make_manager()
        with pytest.raises(HTTPError):
            _collect(_source("events", manager))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Humanitix API key"),
            ("forbidden", 403, False, "Invalid Humanitix API key"),
            ("server_error", 500, False, "Humanitix returned HTTP 500"),
        ]
    )
    @mock.patch(HUMANITIX_SESSION_PATCH)
    def test_status_mapping(self, _name, status, expected_valid, expected_message, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("hmtx-key") == (expected_valid, expected_message)

    @mock.patch(HUMANITIX_SESSION_PATCH)
    def test_unreachable_probe_maps_to_generic_message(self, mock_session) -> None:
        # validate_via_probe swallows transport errors and reports no status; surface a generic message.
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("hmtx-key") == (False, "Could not validate Humanitix API key")


class TestSourceResponse:
    @parameterized.expand([("events",), ("tags",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_uses_id_primary_key(self, endpoint, MockSession) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["_id"]
        # Every endpoint is full refresh only, so there is no datetime partitioning.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        # Humanitix Mongo `_id`s are globally unique, so a single `_id` key is sufficient table-wide.
        assert all(config.primary_keys == ["_id"] for config in HUMANITIX_ENDPOINTS.values())
        assert set(HUMANITIX_ENDPOINTS) == set(ENDPOINTS)
