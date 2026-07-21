import json
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory import inflowinventory
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.inflowinventory import (
    INFLOWINVENTORY_API_VERSION,
    PAGE_SIZE,
    InflowInventoryResumeConfig,
    check_access,
    inflowinventory_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.settings import (
    ENDPOINTS,
    INFLOWINVENTORY_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
DEFAULT_URL = "https://cloudapi.inflowinventory.com/co-123/products"


def _json_response(body: Any, *, status: int = 200, url: str = DEFAULT_URL, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = url
    resp.reason = reason
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: InflowInventoryResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params + url AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead. ``prepared.url``
    must be a real host string because the client's SSRF host-pinning inspects it before sending.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        snapshots.append({"params": dict(request.params or {}), "url": request.url})
        prepared = MagicMock()
        prepared.url = DEFAULT_URL
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _full_page(start_id: int, id_field: str = "productId") -> list[dict[str, Any]]:
    return [{id_field: str(start_id + i)} for i in range(PAGE_SIZE)]


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: MagicMock) -> Any:
    return inflowinventory_source(
        api_key="inflow-key",
        company_id="co-123",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_yields_and_stops(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response([{"productId": "1"}, {"productId": "2"}])])

        manager = _make_manager()
        rows = _rows(_source("products", manager))

        assert rows == [{"productId": "1"}, {"productId": "2"}]
        assert session.send.call_count == 1
        # The page is short (< PAGE_SIZE), so we stop without persisting resume state.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_after_cursor_until_short_page(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        # Last row of the first full page has productId str(PAGE_SIZE - 1), which becomes the cursor.
        last_id = str(PAGE_SIZE - 1)
        snapshots = _wire(session, [_json_response(_full_page(0)), _json_response([{"productId": "9999"}])])

        manager = _make_manager()
        rows = _rows(_source("products", manager))

        assert len(rows) == PAGE_SIZE + 1
        assert snapshots[0]["params"] == {"count": PAGE_SIZE}
        assert snapshots[1]["params"] == {"count": PAGE_SIZE, "after": last_id}
        # Checkpoint saved after the first full page (points at the next page); the short page ends it.
        manager.save_state.assert_called_once_with(InflowInventoryResumeConfig(after=last_id))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_uses_per_endpoint_id_field(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        last_id = str(PAGE_SIZE - 1)
        snapshots = _wire(
            session,
            [_json_response(_full_page(0, id_field="customerId")), _json_response([{"customerId": "9999"}])],
        )

        _rows(_source("customers", _make_manager()))
        assert snapshots[1]["params"]["after"] == last_id

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        # The unpaginated first page (after absent) must never be fetched on resume.
        snapshots = _wire(session, [_json_response([{"productId": "5"}])])

        rows = _rows(_source("products", _make_manager(InflowInventoryResumeConfig(after="42"))))

        assert rows == [{"productId": "5"}]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["after"] == "42"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response([])])

        manager = _make_manager()
        rows = _rows(_source("products", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_missing_id_field_stops(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        # A full page whose last row lacks the cursor field can't be paginated past — stop instead
        # of looping forever on the same cursor.
        page = _full_page(0)
        page[-1] = {"name": "no id here"}
        _wire(session, [_json_response(page)])

        manager = _make_manager()
        rows = _rows(_source("products", manager))

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_request_sends_count_and_no_after(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_json_response([])])

        _rows(_source("products", _make_manager()))
        assert snapshots[0]["params"] == {"count": PAGE_SIZE}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_targets_company_scoped_url(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_json_response([])])

        _rows(_source("sales_orders", _make_manager()))
        assert snapshots[0]["url"] == "https://cloudapi.inflowinventory.com/co-123/sales-orders"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_version_header_is_set_on_session(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response([])])

        _rows(_source("products", _make_manager()))
        assert session.headers.get("Accept") == f"application/json;version={INFLOWINVENTORY_API_VERSION}"

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_reissued(
        self, _name: str, status: int, MockSession: MagicMock, _sleep: MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response([], status=status), _json_response([])])

        rows = _rows(_source("products", _make_manager()))
        # A 429/5xx is retried (not permanently failed): the second attempt succeeds with an empty page.
        assert rows == []
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises(self, _name: str, status: int, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response([], status=status, reason="Client Error")])

        with pytest.raises(requests.HTTPError):
            _rows(_source("products", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_raises_value_error(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        # A 200 whose body isn't the expected bare array is a permanent contract violation.
        _wire(session, [_json_response({"error": "nope"})])

        with pytest.raises(ValueError):
            _rows(_source("products", _make_manager()))


class TestCheckAccess:
    @staticmethod
    def _build_session(response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    def _patch_session(self, monkeypatch: Any, response: Any) -> MagicMock:
        session = self._build_session(response)
        monkeypatch.setattr(inflowinventory, "make_tracked_session", lambda **kwargs: session)
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "inFlow Inventory returned HTTP 500"),
        ]
    )
    @mock.patch.object(inflowinventory, "make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_make_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        mock_make_session.return_value = self._build_session(response)
        assert check_access("inflow-key", "co-123") == (expected_status, expected_message)

    def test_malformed_company_id_short_circuits(self, monkeypatch: Any) -> None:
        # A bad company ID never reaches the network — no session is created.
        session = self._patch_session(monkeypatch, MagicMock())
        status, message = check_access("inflow-key", "bad id/../evil")
        assert status == 400
        assert message is not None
        session.get.assert_not_called()

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("inflow-key", "co-123")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid inFlow Inventory API key"),
            ("forbidden", 403, False, "Invalid inFlow Inventory API key"),
            ("server_error", 500, False, "inFlow Inventory returned HTTP 500"),
        ]
    )
    @mock.patch.object(inflowinventory, "make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_make_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_make_session.return_value = self._build_session(response)
        assert validate_credentials("inflow-key", "co-123") == (expected_valid, expected_message)


class TestInflowInventorySourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == INFLOWINVENTORY_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_primary_key_matches_id_field(self) -> None:
        assert all(config.primary_keys == [config.id_field] for config in INFLOWINVENTORY_ENDPOINTS.values())
        assert set(INFLOWINVENTORY_ENDPOINTS) == set(ENDPOINTS)
