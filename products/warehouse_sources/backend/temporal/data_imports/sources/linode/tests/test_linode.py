import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linode.linode import (
    PAGE_SIZE,
    LinodeResumeConfig,
    _build_x_filter,
    _format_filter_value,
    linode_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linode.settings import LINODE_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the linode module.
LINODE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.linode.linode.make_tracked_session"
)
# Skip tenacity's backoff so retry tests don't actually sleep.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(
    items: Optional[list[dict[str, Any]]],
    *,
    page: int = 1,
    pages: int = 1,
    status: int = 200,
    drop_data: bool = False,
    content: Optional[bytes] = None,
) -> Response:
    resp = Response()
    resp.status_code = status
    if content is not None:
        resp._content = content
        return resp
    body: dict[str, Any] = {"page": page, "pages": pages, "results": len(items or [])}
    if not drop_data:
        body["data"] = items or []
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: LinodeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

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


def _source(endpoint: str = "volumes", manager: mock.MagicMock | None = None, **kwargs: Any) -> Any:
    return linode_source(
        api_token="tok",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatFilterValue:
    @parameterized.expand(
        [
            ("integer_passthrough", 12345, 12345),
            ("string_passthrough", "abc", "abc"),
            ("aware_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
        ]
    )
    def test_format_filter_value(self, _name: str, value: Any, expected: Any) -> None:
        # A "+00:00" offset in the filter value would make Linode reject the X-Filter, so datetimes
        # must render without one.
        assert _format_filter_value(value) == expected


class TestBuildXFilter:
    def test_first_sync_has_no_gte_bound(self) -> None:
        # A missing watermark must produce an order-only filter, never `{"+gte": None}`, which the API
        # would reject and wedge every first sync.
        assert _build_x_filter("id", None) == {"+order_by": "id", "+order": "asc"}

    def test_watermark_adds_ascending_gte_bound(self) -> None:
        # Ordering must always be ascending so rows arrive oldest-first, matching sort_mode="asc";
        # otherwise the watermark would checkpoint to ~now after the first batch.
        assert _build_x_filter("date", datetime(2026, 3, 4, 2, 58, 14)) == {
            "+order_by": "date",
            "+order": "asc",
            "date": {"+gte": "2026-03-04T02:58:14"},
        }


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True),
            ("invalid_token", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        with mock.patch(LINODE_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = response
            valid, _message = validate_credentials("tok")
        assert valid is expected_valid

    def test_network_error_is_not_valid(self) -> None:
        with mock.patch(LINODE_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
            valid, message = validate_credentials("tok")
        assert valid is False
        assert message is not None

    def test_token_is_registered_for_redaction(self) -> None:
        # The PAT rides in an Authorization header the value-based scrubber can only mask if the token
        # is registered via redact_values; dropping it would leak the credential into HTTP telemetry.
        response = mock.MagicMock()
        response.status_code = 200
        with mock.patch(LINODE_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = response
            validate_credentials("tok")
        assert mock_session.call_args.kwargs["redact_values"] == ("tok",)

    def test_error_status_does_not_leak_response_body(self) -> None:
        # Linode error bodies can echo account data; the persisted validation message must not carry it.
        response = mock.MagicMock()
        response.status_code = 500
        response.text = "secret account details"
        with mock.patch(LINODE_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = response
            _valid, message = validate_credentials("tok")
        assert message is not None
        assert "secret account details" not in message


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_across_all_pages(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}], page=1, pages=2),
                _response([{"id": 3}], page=2, pages=2),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert params[0]["page"] == 1
        assert params[0]["page_size"] == PAGE_SIZE
        assert params[1]["page"] == 2
        # Checkpoint saved after the first page (points at the next page); the last page ends it.
        manager.save_state.assert_called_once_with(LinodeResumeConfig(next_page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        # Only page 2 is wired, so resuming anywhere other than page 2 fails loudly (StopIteration).
        params = _wire(session, [_response([{"id": 3}], page=2, pages=2)])

        manager = _make_manager(LinodeResumeConfig(next_page=2))
        rows = _rows(_source(manager=manager))

        assert params[0]["page"] == 2
        assert [r["id"] for r in rows] == [3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sends_no_x_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], pages=1)])

        _rows(
            _source(
                endpoint="volumes",
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )
        assert "X-Filter" not in session.headers

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_endpoint_attaches_x_filter_with_watermark(self, MockSession: mock.MagicMock) -> None:
        # A regression that stops threading the watermark into the X-Filter would silently revert
        # incremental events to a full refresh; assert the id `+gte` bound is present on the request.
        session = MockSession.return_value
        _wire(session, [_response([{"id": 5}], pages=1)])

        _rows(
            _source(
                endpoint="events",
                should_use_incremental_field=True,
                db_incremental_field_last_value=4,
                incremental_field="id",
            )
        )
        assert json.loads(session.headers["X-Filter"]) == {"+order_by": "id", "+order": "asc", "id": {"+gte": 4}}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_page_size_is_maxed(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}], pages=1)])

        _rows(_source())
        assert params[0]["page_size"] == PAGE_SIZE
        assert PAGE_SIZE == 500

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sync_session_registers_token_for_redaction(self, MockSession: mock.MagicMock) -> None:
        # The PAT rides on the Authorization header of every paginated request, so it must be
        # registered for value-based masking in HTTP telemetry.
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], pages=1)])

        _rows(_source())
        assert MockSession.call_args.kwargs["redact_values"] == ("tok",)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoint_advances_per_committed_page(self, MockSession: mock.MagicMock) -> None:
        # Each page is yielded (and committed downstream) before its checkpoint is saved, and the
        # checkpoint points at the NEXT unfetched page — so a crash resumes there without re-fetching
        # committed rows or skipping any (the guarantee the append-only endpoints rely on). The final
        # page has no next page, so it saves nothing.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 1}], page=1, pages=3),
                _response([{"id": 2}], page=2, pages=3),
                _response([{"id": 3}], page=3, pages=3),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert manager.save_state.call_args_list == [
            mock.call(LinodeResumeConfig(next_page=2)),
            mock.call(LinodeResumeConfig(next_page=3)),
        ]


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_reraised(
        self, _name: str, status_code: int, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, status=status_code, content=b"{}") for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_source())

        # 5 attempts before giving up (reraise=True).
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transient_error_retried_then_succeeds(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, status=500, content=b"{}"), _response([{"id": 1}], pages=1)])

        rows = _rows(_source())

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_message_excludes_response_body(self, MockSession: mock.MagicMock) -> None:
        # Error bodies can carry account/billing/audit data; a failing sync must not copy the raw body
        # into the raised (and later persisted) error message.
        session = MockSession.return_value
        _wire(session, [_response(None, status=404, content=b'{"errors":[{"reason":"secret account details"}]}')])

        with pytest.raises(Exception) as exc_info:
            _rows(_source())
        assert "secret account details" not in str(exc_info.value)


class TestLinodeSource:
    def test_sort_mode_is_ascending(self) -> None:
        assert _source(endpoint="events").sort_mode == "asc"

    @parameterized.expand(
        [
            ("invoices", "date", True),
            ("events", "created", True),
            ("domains", None, False),
            ("users", None, False),
        ]
    )
    def test_partitioning_matches_stable_field(
        self, endpoint: str, partition_key: str | None, partitioned: bool
    ) -> None:
        response = _source(endpoint=endpoint)
        if partitioned:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None

    def test_primary_keys_come_from_endpoint_config(self) -> None:
        assert _source(endpoint="users").primary_keys == ["username"]
        assert LINODE_ENDPOINTS["events"].primary_keys == ["id"]
