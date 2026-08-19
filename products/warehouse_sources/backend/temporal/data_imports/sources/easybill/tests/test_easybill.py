import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.easybill import (
    EasybillResumeConfig,
    date_range_since,
    easybill_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.settings import EASYBILL_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the easybill module.
EASYBILL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.easybill.easybill.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None,
    *,
    page: int = 1,
    pages: int = 1,
    status: int = 200,
    body_override: dict[str, Any] | None = None,
) -> Response:
    body: dict[str, Any] = (
        body_override
        if body_override is not None
        else {
            "page": page,
            "pages": pages,
            "limit": 1000,
            "total": len(items or []),
            "items": items or [],
        }
    )
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: EasybillResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    would only show the final state — snapshot a copy when each request is prepared instead.
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


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return easybill_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


class TestDateRangeSince:
    @parameterized.expand(
        [
            ("datetime", datetime(2024, 3, 10, 12, 0, tzinfo=UTC), f"2024-03-09,{date.today().isoformat()}"),
            ("date", date(2024, 3, 10), f"2024-03-09,{date.today().isoformat()}"),
            ("iso_string", "2024-03-10T00:00:00+00:00", f"2024-03-09,{date.today().isoformat()}"),
            ("iso_string_z", "2024-03-10T00:00:00Z", f"2024-03-09,{date.today().isoformat()}"),
            ("plain_date_string", "2024-03-10", f"2024-03-09,{date.today().isoformat()}"),
            ("none", None, None),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_date_range_since(self, _name: str, value: Any, expected: str | None) -> None:
        assert date_range_since(value) == expected


class TestIncrementalParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_documents_incremental_adds_edited_at_range(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}], pages=1)])

        _rows(
            _source(
                "Documents",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2024, 3, 10),
            )
        )

        assert params[0]["edited_at"] == f"2024-03-09,{date.today().isoformat()}"
        assert params[0]["limit"] == 1000
        assert params[0]["page"] == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_documents_first_sync_omits_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}], pages=1)])

        _rows(
            _source(
                "Documents",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
            )
        )

        assert "edited_at" not in params[0]

    @parameterized.expand(["DocumentPayments", "Customers", "Positions", "Projects", "CustomerGroups"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_incremental_endpoints_never_filter(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}], pages=1)])

        _rows(
            _source(
                endpoint,
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2024, 3, 10),
            )
        )

        assert "edited_at" not in params[0]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_last_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": 1}], page=1, pages=2),
                _response([{"id": 2}], page=2, pages=2),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("Customers", manager))

        assert [r["id"] for r in rows] == [1, 2]
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        assert session.send.call_count == 2
        manager.save_state.assert_called_once_with(EasybillResumeConfig(page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_makes_one_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], page=1, pages=1)])

        manager = _make_manager()
        rows = _rows(_source("Customers", manager))

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], page=1, pages=1)])

        rows = _rows(_source("Customers", _make_manager()))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 2}], page=2, pages=2)])

        manager = _make_manager(EasybillResumeConfig(page=2))
        rows = _rows(_source("Customers", manager))

        assert [r["id"] for r in rows] == [2]
        assert params[0]["page"] == 2
        assert session.send.call_count == 1


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("Documents", "documents", "created_at"),
            ("Customers", "customers", "created_at"),
            ("Positions", "positions", None),
            ("Projects", "projects", None),
            ("CustomerGroups", "customer_groups", None),
            ("DocumentPayments", "document_payments", None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_shape(
        self,
        endpoint: str,
        table_name: str,
        partition_key: str | None,
        MockSession,
    ) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert EASYBILL_ENDPOINTS[endpoint].table_name == table_name
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [partition_key]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        with mock.patch(EASYBILL_SESSION_PATCH, return_value=session):
            assert validate_credentials("key") is expected

    def test_network_error_is_false(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(EASYBILL_SESSION_PATCH, return_value=session):
            assert validate_credentials("key") is False


class TestRetryAndErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status_code: int, MockSession, _sleep) -> None:
        # easybill enforces a strict per-minute rate limit (10/min on PLUS, 60/min on BUSINESS)
        # returned as 429; the shared client retries on status so one throttle doesn't fail the sync.
        session = MockSession.return_value
        transient = _response(None, status=status_code, body_override={"error": "transient"})
        ok = _response([{"id": 1}], page=1, pages=1)
        _wire(session, [transient, ok])

        rows = _rows(_source("Customers", _make_manager()))

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        resp = _response(None, status=401, body_override={"error": "unauthorized"})
        resp.url = "https://api.easybill.de/rest/v1/customers"
        _wire(session, [resp])

        with pytest.raises(HTTPError):
            _rows(_source("Customers", _make_manager()))


if __name__ == "__main__":
    pytest.main([__file__])
