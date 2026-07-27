import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.cloudbeds import (
    PAGE_SIZE,
    CloudbedsResumeConfig,
    cloudbeds_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.settings import (
    CLOUDBEDS_ENDPOINTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the cloudbeds module.
CLOUDBEDS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.cloudbeds.make_tracked_session"
)


def _response(
    rows: list[dict[str, Any]] | None,
    *,
    status: int = 200,
    drop_data: bool = False,
    body: dict[str, Any] | None = None,
    url: str = "https://api.cloudbeds.com/api/v1.2/getReservations",
    reason: str = "OK",
) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = url
    resp.reason = reason
    if body is not None:
        payload: Any = body
    elif drop_data:
        # A 200 body without `data` — a `success: false` error envelope or a changed shape.
        payload = {"success": True}
    else:
        items = rows or []
        payload = {"success": True, "data": items, "count": len(items), "total": len(items)}
    resp._content = json.dumps(payload).encode()
    return resp


def _make_manager(resume_state: CloudbedsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(
    endpoint: str = "reservations",
    *,
    manager: mock.MagicMock | None = None,
    property_id: str | None = None,
) -> Any:
    return cloudbeds_source(
        api_key="cbat_key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        property_id=property_id,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    def _full_page(self, start: int) -> list[dict[str, Any]]:
        return [{"reservationID": str(start + i)} for i in range(PAGE_SIZE)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_by_page_number_and_checkpoints_after_full_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(self._full_page(0)), _response([{"reservationID": "999"}])])

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert len(rows) == PAGE_SIZE + 1
        assert params[0]["pageNumber"] == 1
        assert params[0]["pageSize"] == PAGE_SIZE
        assert params[1]["pageNumber"] == 2
        # Checkpoint saved after the first full page (points at page 2); the short page then ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == CloudbedsResumeConfig(page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"reservationID": "1"}, {"reservationID": "2"}])])

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert [r["reservationID"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"reservationID": "5"}])])

        rows = _rows(_source(manager=_make_manager(CloudbedsResumeConfig(page=3))))

        assert rows == [{"reservationID": "5"}]
        # Page 1 and 2 must never be fetched on resume.
        assert [p["pageNumber"] for p in params] == [3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_property_id_is_sent_on_every_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(self._full_page(0)), _response([])])

        _rows(_source(manager=_make_manager(), property_id="12345"))

        assert all(p["propertyID"] == "12345" for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_endpoint_fetches_once_without_page_params(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"propertyID": "1"}, {"propertyID": "2"}])])

        manager = _make_manager()
        rows = _rows(_source("hotels", manager=manager))

        assert rows == [{"propertyID": "1"}, {"propertyID": "2"}]
        assert session.send.call_count == 1
        assert "pageNumber" not in params[0]
        assert "pageSize" not in params[0]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rooms_are_flattened_with_property_id(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    [
                        {
                            "propertyID": "1",
                            "propertyName": "Hotel One",
                            "rooms": [{"roomID": "r1", "roomName": "101"}, {"roomID": "r2", "roomName": "102"}],
                        },
                        {"propertyID": "2", "propertyName": "Hotel Two", "rooms": []},
                    ]
                )
            ],
        )

        rows = _rows(_source("rooms", manager=_make_manager()))

        # Each nested room becomes its own row with the parent propertyID copied in; the parent with
        # an empty `rooms` list contributes nothing.
        assert rows == [
            {"roomID": "r1", "roomName": "101", "propertyID": "1"},
            {"roomID": "r2", "roomName": "102", "propertyID": "1"},
        ]


class TestFailLoud:
    @parameterized.expand(
        [("missing_data_key", {"success": True}), ("success_false", {"success": False, "message": "Access denied"})]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_fails_loud(self, _name: str, body: dict[str, Any], MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, body=body)])

        # A 200 body without `data` (a `success: false` envelope or a changed shape) must fail loud,
        # not silently sync 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(manager=_make_manager()))

    @parameterized.expand(
        [
            ("unauthorized", 401, "Unauthorized"),
            ("forbidden", 403, "Forbidden"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_failure_raises_matchable_error(
        self, _name: str, status: int, reason: str, MockSession: mock.MagicMock
    ) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.source import CloudbedsSource

        session = MockSession.return_value
        url = f"https://api.cloudbeds.com/api/v1.2/getReservations?pageNumber=1&pageSize={PAGE_SIZE}"
        _wire(session, [_response(None, status=status, url=url, reason=reason)])

        with pytest.raises(Exception) as exc_info:
            _rows(_source(manager=_make_manager()))

        message = str(exc_info.value)
        # The stable "<status> Client Error: <reason> for url: https://api.cloudbeds.com" prefix is
        # what get_non_retryable_errors matches on to surface an actionable message.
        assert message.startswith(f"{status} Client Error: {reason} for url: https://api.cloudbeds.com")
        assert any(key in message for key in CloudbedsSource().get_non_retryable_errors())

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_is_never_leaked_into_error(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        # Even if a future credential rides in the query string, the framework redacts the configured
        # secret value out of every raised error message.
        url = "https://api.cloudbeds.com/api/v1.2/getReservations?api_key=cbat_key&pageNumber=1"
        _wire(session, [_response(None, status=401, url=url, reason="Unauthorized")])

        with pytest.raises(Exception) as exc_info:
            _rows(_source(manager=_make_manager()))

        assert "cbat_key" not in str(exc_info.value)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Cloudbeds API key"),
            ("forbidden", 403, False, "Invalid Cloudbeds API key"),
            ("server_error", 500, False, "Cloudbeds returned HTTP 500"),
        ]
    )
    @mock.patch(CLOUDBEDS_SESSION_PATCH)
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("cbat_key") == (expected_valid, expected_message)

    @mock.patch(CLOUDBEDS_SESSION_PATCH)
    def test_connection_error_is_not_valid(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("cbat_key") == (False, "Could not connect to Cloudbeds")

    @mock.patch(CLOUDBEDS_SESSION_PATCH)
    def test_probe_scopes_to_property_when_configured(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("cbat_key", property_id="12345")
        called_url = mock_session.return_value.get.call_args.args[0]
        assert "propertyID=12345" in called_url


class TestCloudbedsSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint, manager=_make_manager())
        assert response.name == endpoint
        assert response.primary_keys == CLOUDBEDS_ENDPOINTS[endpoint].primary_keys
        # No creation timestamp is verified stable across every object, so we don't partition.
        assert response.partition_mode is None

    def test_endpoint_catalog_is_consistent(self) -> None:
        assert set(CLOUDBEDS_ENDPOINTS) == set(ENDPOINTS)
        assert all(config.primary_keys for config in CLOUDBEDS_ENDPOINTS.values())
