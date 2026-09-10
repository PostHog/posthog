import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.flexmail import (
    PAGE_SIZE,
    FlexmailResumeConfig,
    flexmail_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.settings import (
    ENDPOINTS,
    FLEXMAIL_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the flexmail module.
FLEXMAIL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.flexmail.make_tracked_session"
)
# tenacity sleeps between the client's own retries — patch it so retry tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _json_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _envelope(items: list[dict[str, Any]], total: int, offset: int = 0) -> Response:
    # Flexmail's HAL collection envelope: rows under `_embedded.item`, row count in `total`.
    return _json_response({"total": total, "limit": PAGE_SIZE, "offset": offset, "_embedded": {"item": items}})


def _make_manager(resume_state: FlexmailResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's query params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages (the paginator rewrites the
    offset), so inspecting it after the run shows only the final state — snapshot a copy when each
    request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _pages(source_response):
    yield from source_response.items()


def _source(endpoint: str, manager: mock.MagicMock | None = None):
    return flexmail_source(
        account_id="12345",
        personal_access_token="flexmail-token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager or _make_manager(),
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_and_stops_without_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_envelope([{"id": 1}, {"id": 2}], total=2)])

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        # `total` is within the first page, so we stop without persisting resume state.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_request_starts_at_offset_zero_with_page_size(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_envelope([{"id": 1}], total=1)])

        _rows(_source("contacts"))

        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_offset_pagination_until_total(self, MockSession) -> None:
        session = MockSession.return_value
        first_page = [{"id": i} for i in range(PAGE_SIZE)]
        params = _wire(
            session,
            [
                _envelope(first_page, total=PAGE_SIZE + 1),
                _envelope([{"id": 999}], total=PAGE_SIZE + 1, offset=PAGE_SIZE),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert len(rows) == PAGE_SIZE + 1
        assert [p["offset"] for p in params] == [0, PAGE_SIZE]
        # State is saved after the first page (points at the next offset), then we stop.
        assert [s.offset for s in (c.args[0] for c in manager.save_state.call_args_list)] == [PAGE_SIZE]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_envelope([], total=0)])

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_mid_collection_stops(self, MockSession) -> None:
        # Rows deleted mid-sync can shrink the collection; an empty page must terminate the loop even
        # when `total` still claims more rows.
        session = MockSession.return_value
        _wire(session, [_envelope([], total=PAGE_SIZE * 2)])

        rows = _rows(_source("contacts"))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_embedded_key_yields_nothing(self, MockSession) -> None:
        # HAL omits `_embedded` entirely for an empty collection — that's a valid zero-row page, not
        # an error.
        session = MockSession.return_value
        _wire(session, [_json_response({"total": 0, "limit": PAGE_SIZE, "offset": 0})])

        rows = _rows(_source("contacts"))

        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_links_are_stripped_from_rows(self, MockSession) -> None:
        session = MockSession.return_value
        items = [{"id": 1, "email": "a@b.co", "_links": {"self": {"href": "/contacts/1"}}}]
        _wire(session, [_envelope(items, total=1)])

        rows = _rows(_source("contacts"))

        assert rows == [{"id": 1, "email": "a@b.co"}]


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_envelope([{"id": 5}], total=PAGE_SIZE + 1, offset=PAGE_SIZE)])

        manager = _make_manager(FlexmailResumeConfig(offset=PAGE_SIZE))
        rows = _rows(_source("contacts", manager))

        assert rows == [{"id": 5}]
        # The initial (offset=0) page must never be fetched on resume.
        assert [p["offset"] for p in params] == [PAGE_SIZE]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_state_saved_only_after_page_is_yielded_carrying_next_offset(self, MockSession) -> None:
        session = MockSession.return_value
        first_page = [{"id": i} for i in range(PAGE_SIZE)]
        _wire(
            session,
            [
                _envelope(first_page, total=PAGE_SIZE + 1),
                _envelope([{"id": 999}], total=PAGE_SIZE + 1, offset=PAGE_SIZE),
            ],
        )
        manager = _make_manager()

        pages = iter(_pages(_source("contacts", manager)))

        assert len(next(pages)) == PAGE_SIZE
        # A crash here must re-fetch page 1 (nothing persisted yet), not skip it.
        manager.save_state.assert_not_called()

        assert next(pages) == [{"id": 999}]
        # After page 1 is yielded the checkpoint points at the NEXT offset.
        assert manager.save_state.call_args.args[0] == FlexmailResumeConfig(offset=PAGE_SIZE)


class TestUnpaginatedEndpoints:
    @parameterized.expand([("segments",), ("opt_in_forms",), ("custom_fields",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fetches_once_never_paginates_and_strips_links(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        items = [{"id": "u-1", "_links": {"self": {"href": "/x"}}}]
        params = _wire(session, [_json_response({"_embedded": {"item": items}})])

        manager = _make_manager()
        rows = _rows(_source(endpoint, manager))

        assert rows == [{"id": "u-1"}]
        # A single request with no pagination params, and no resume state persisted.
        assert session.send.call_count == 1
        assert "offset" not in params[0] and "limit" not in params[0]
        manager.save_state.assert_not_called()


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_succeed(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response({}, status_code=status), _envelope([{"id": 1}], total=1)])

        rows = _rows(_source("contacts"))

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response({"error": "nope"}, status_code=status)])

        with pytest.raises(Exception):
            _rows(_source("contacts"))


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Flexmail account ID or personal access token"),
            ("forbidden", 403, False, "Invalid Flexmail account ID or personal access token"),
            ("server_error", 500, False, "Flexmail returned HTTP 500"),
        ]
    )
    @mock.patch(FLEXMAIL_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None, mock_session: mock.MagicMock
    ) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        mock_session.return_value = session
        assert validate_credentials("12345", "flexmail-token") == (expected_valid, expected_message)

    @mock.patch(FLEXMAIL_SESSION_PATCH)
    def test_transport_error_is_not_validated(self, mock_session: mock.MagicMock) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        mock_session.return_value = session
        assert validate_credentials("12345", "flexmail-token") == (False, "Could not validate Flexmail credentials")

    @mock.patch(FLEXMAIL_SESSION_PATCH)
    def test_probe_uses_basic_auth(self, mock_session: mock.MagicMock) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        mock_session.return_value = session
        validate_credentials("12345", "flexmail-token")
        _args, kwargs = session.get.call_args
        assert kwargs["auth"] == HTTPBasicAuth("12345", "flexmail-token")


class TestFlexmailSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp exists on most resources, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in FLEXMAIL_ENDPOINTS.values())
        assert set(FLEXMAIL_ENDPOINTS) == set(ENDPOINTS)
