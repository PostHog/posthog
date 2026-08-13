import json
import time
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.shopwired import (
    ShopWiredResumeConfig,
    shopwired_source,
    to_unix_timestamp,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the shopwired module.
SHOPWIRED_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.shopwired.make_tracked_session"
)


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _full_page(start_id: int) -> list[dict[str, Any]]:
    return [{"id": start_id + i} for i in range(PAGE_SIZE)]


def _make_manager(resume_state: ShopWiredResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting the shared dict after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return shopwired_source(
        api_key="sw-key",
        api_secret="sw-secret",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_full_page(0)), _response([{"id": 999}])])

        manager = _make_manager()
        rows = _rows(_source("products", manager))

        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1] == {"id": 999}
        # count/offset are ShopWired's pagination params (limit_param="count").
        assert params[0]["offset"] == 0
        assert params[0]["count"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE
        # Checkpoint saved once after the full first page (points at the next page); short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ShopWiredResumeConfig(offset=PAGE_SIZE, from_timestamp=None)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}])])

        manager = _make_manager()
        rows = _rows(_source("products", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source("products", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset_and_pinned_window(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 5}])])

        manager = _make_manager(ShopWiredResumeConfig(offset=200, from_timestamp=1700000000))
        rows = _rows(
            _source(
                "orders",
                manager,
                should_use_incremental_field=True,
                # A watermark that advanced mid-run must not replace the pinned window from resume state.
                db_incremental_field_last_value=datetime(2024, 6, 1, tzinfo=UTC),
            )
        )

        assert rows == [{"id": 5}]
        assert params[0]["offset"] == 200
        assert params[0]["from"] == 1700000000


class TestIncrementalParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_run_sends_from_and_sort(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}])])

        watermark = datetime(2024, 1, 1, tzinfo=UTC)
        _rows(
            _source(
                "orders",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )
        )

        assert params[0]["from"] == int(watermark.timestamp())
        assert params[0]["sort"] == "date"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_run_omits_from_and_sort(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}])])

        _rows(_source("products", _make_manager()))

        assert "from" not in params[0]
        assert "sort" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_orders_full_refresh_omits_from_but_keeps_sort(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}])])

        # Orders always sort by date so the ascending watermark advances correctly, even on a full
        # refresh where no `from` window is applied.
        _rows(_source("orders", _make_manager(), should_use_incremental_field=False))

        assert "from" not in params[0]
        assert params[0]["sort"] == "date"


class TestUnpaginatedEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_order_statuses_fetches_once_without_pagination_params(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        # A full-size page must not trigger a second request — order statuses document no pagination.
        params = _wire(session, [_response(_full_page(0))])

        manager = _make_manager()
        rows = _rows(_source("order_statuses", manager))

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1
        assert params[0] == {}
        manager.save_state.assert_not_called()


class TestErrorClassification:
    @staticmethod
    def _no_sleep() -> Any:
        # The client retries retryable errors with exponential backoff; neutralize the sleep so
        # retry-path tests stay instant and deterministic.
        return mock.patch.object(RESTClient._send_request.retry, "sleep", lambda *a, **k: None)  # type: ignore[attr-defined]

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise(self, _name: str, status: int, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "nope"}, status=status)])

        # 4xx is permanent — it must surface (not retry, not silently sync 0 rows).
        with pytest.raises(HTTPError):
            _rows(_source("products", _make_manager()))
        assert session.send.call_count == 1

    @parameterized.expand([("server_error", 500), ("service_unavailable", 503), ("rate_limited", 429)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_succeed(
        self, _name: str, status: int, MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status), _response([{"id": 1}])])

        with self._no_sleep():
            rows = _rows(_source("products", _make_manager()))

        assert rows == [{"id": 1}]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_is_retried_not_yielded(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        # A 200 whose body isn't the expected bare array is treated as transient and retried rather
        # than wrapped as a single stray row.
        _wire(session, [_response({"error": "unexpected"}), _response([{"id": 1}])])

        with self._no_sleep():
            rows = _rows(_source("products", _make_manager()))

        assert rows == [{"id": 1}]
        assert session.send.call_count == 2


class TestToUnixTimestamp:
    @parameterized.expand(
        [
            ("none", None, None),
            ("datetime", datetime(2024, 1, 1, tzinfo=UTC), 1704067200),
            # Naive values must be treated as UTC regardless of the worker's local timezone.
            ("naive_datetime", datetime(2024, 1, 1), 1704067200),
            ("date", date(2024, 1, 1), 1704067200),
            ("epoch_int", 1704067200, 1704067200),
            ("epoch_float", 1704067200.5, 1704067200),
            ("rfc2822_string", "Mon, 01 Jan 2024 00:00:00 +0000", 1704067200),
            ("iso_string", "2024-01-01T00:00:00+00:00", 1704067200),
            ("naive_iso_string", "2024-01-01T00:00:00", 1704067200),
            ("unparseable_string", "not-a-date-at-all-99", None),
            ("empty_string", "", None),
            ("bool", True, None),
        ]
    )
    def test_conversion(self, _name: str, value: Any, expected: int | None) -> None:
        assert to_unix_timestamp(value) == expected

    def test_naive_values_are_utc_regardless_of_local_timezone(self, monkeypatch: Any) -> None:
        # CI runs in UTC, where a local-time interpretation of naive values happens to give the
        # right answer — force a non-UTC timezone so a regression to naive .timestamp() fails here.
        monkeypatch.setenv("TZ", "America/New_York")
        time.tzset()
        try:
            assert to_unix_timestamp(date(2024, 1, 1)) == 1704067200
            assert to_unix_timestamp(datetime(2024, 1, 1)) == 1704067200
            assert to_unix_timestamp("2024-01-01T00:00:00") == 1704067200
        finally:
            monkeypatch.undo()
            time.tzset()


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid ShopWired API key or secret"),
            ("forbidden", 403, False, "Invalid ShopWired API key or secret"),
            ("server_error", 500, False, "ShopWired returned HTTP 500"),
        ]
    )
    @mock.patch(SHOPWIRED_SESSION_PATCH)
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("sw-key", "sw-secret") == (expected_valid, expected_message)

    @mock.patch(SHOPWIRED_SESSION_PATCH)
    def test_connection_error_is_not_valid(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        valid, message = validate_credentials("sw-key", "sw-secret")
        assert valid is False
        assert message == "Could not connect to ShopWired"


class TestShopWiredSourceResponse:
    @parameterized.expand([("products",), ("orders",), ("order_statuses",), ("vouchers",)])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_count == 1
        assert response.partition_size == 1

    def test_orders_partition_on_stable_created_field(self) -> None:
        response = _source("orders", _make_manager())
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["created"]

    def test_non_order_endpoints_have_no_datetime_partition(self) -> None:
        response = _source("products", _make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None
