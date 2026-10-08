import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

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


class TestContactFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_which_contacts_finished(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _envelope([{"id": 29}], total=1),
                _envelope([{"id": 7, "name": "import"}], total=1),
            ],
        )

        manager = _make_manager()
        _rows(_source("contact_sources", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved, "the fan-out must checkpoint its progress through the contact list"
        assert saved[-1].fanout_state is not None
        assert "/contacts/29/sources" in saved[-1].fanout_state["completed"]


class TestFlexmailSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint)
        assert response.name == endpoint
        # Wired from the endpoint config, not hardcoded: a fan-out table keyed on the bare
        # sub-resource id would seed a duplicate row per contact.
        assert response.primary_keys == FLEXMAIL_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp exists on most resources, so we don't partition.
        assert response.partition_mode is None
