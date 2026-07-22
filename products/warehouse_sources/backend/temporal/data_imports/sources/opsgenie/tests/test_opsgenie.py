import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.opsgenie import (
    PAGE_SIZE,
    OpsgenieResumeConfig,
    _get_headers,
    _to_epoch_ms,
    opsgenie_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.settings import OPSGENIE_ENDPOINTS

OPSGENIE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.opsgenie"
# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source"
    ".rest_client.make_tracked_session"
)


class _FakeManager:
    """In-memory stand-in for ResumableSourceManager that records saved state."""

    def __init__(self, resume_state: Optional[OpsgenieResumeConfig] = None) -> None:
        self._resume_state = resume_state
        self.saved_states: list[OpsgenieResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> Optional[OpsgenieResumeConfig]:
        return self._resume_state

    def save_state(self, data: OpsgenieResumeConfig) -> None:
        self.saved_states.append(data)


def _response(items: list[dict[str, Any]], *, has_next: bool = False, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {}
    if not drop_data:
        body["data"] = items
    if has_next:
        body["paging"] = {"next": "https://api.opsgenie.com/v2/alerts?offset=next"}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _error_response(status: int) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = b"{}"
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting the final state.
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
    endpoint: str,
    manager: _FakeManager,
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Any:
    return opsgenie_source(
        api_key="key",
        region="us",
        endpoint=endpoint,
        team_id=1,
        job_id="job_1",
        resumable_source_manager=manager,  # type: ignore[arg-type]
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToEpochMs:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), 1772593094000),
            (datetime(2026, 3, 4, 2, 58, 14), 1772593094000),
            (date(2026, 3, 4), 1772582400000),
            ("2026-03-04T02:58:14Z", 1772593094000),
            ("2026-03-04T02:58:14+00:00", 1772593094000),
            (1772593094000, 1772593094000),
            ("not-a-date", None),
            (None, None),
        ],
    )
    def test_conversion(self, value: Any, expected: Optional[int]) -> None:
        assert _to_epoch_ms(value) == expected


class TestHeaders:
    def test_genie_key_auth_header(self) -> None:
        assert _get_headers("key_abc")["Authorization"] == "GenieKey key_abc"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_offset(self, MockSession: Any) -> None:
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full_page, has_next=True), _response([{"id": "last"}])])

        manager = _FakeManager()
        rows = _rows(_source("alerts", manager))

        assert [r["id"] for r in rows] == [*(str(i) for i in range(PAGE_SIZE)), "last"]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE
        # State is checkpointed once (the next offset) after the first page; the short final
        # page has no next link, so no further checkpoint is written.
        assert [s.offset for s in manager.saved_states] == [PAGE_SIZE]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_search_endpoint_full_refresh_sends_stable_sort_without_query(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "a"}])])

        _rows(_source("alerts", _FakeManager()))

        assert params[0]["sort"] == "createdAt"
        assert params[0]["order"] == "asc"
        assert "query" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_search_endpoint_incremental_sends_created_at_query(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "a"}])])

        _rows(
            _source(
                "alerts",
                _FakeManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert params[0]["query"] == "createdAt >= 1767225600000"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_search_endpoint_sends_no_sort_or_query(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "u1"}])])

        _rows(
            _source(
                "users",
                _FakeManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert "sort" not in params[0]
        assert "order" not in params[0]
        assert "query" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset_and_window(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "x"}])])

        manager = _FakeManager(resume_state=OpsgenieResumeConfig(offset=PAGE_SIZE, window_start_ms=1700000000000))
        _rows(_source("alerts", manager))

        assert params[0]["offset"] == PAGE_SIZE
        assert params[0]["query"] == "createdAt >= 1700000000000"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_iteration(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], has_next=True)])

        manager = _FakeManager()
        rows = _rows(_source("alerts", manager))

        assert rows == []
        assert session.send.call_count == 1
        assert manager.saved_states == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_without_next_link_stops_iteration(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": str(i)} for i in range(PAGE_SIZE)], has_next=False)])

        rows = _rows(_source("alerts", _FakeManager()))

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_endpoint_fetches_once_without_state(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "team_1"}])])

        manager = _FakeManager()
        rows = _rows(_source("teams", manager))

        assert rows == [{"id": "team_1"}]
        assert session.send.call_count == 1
        assert manager.saved_states == []
        assert "offset" not in params[0]
        assert "limit" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_search_cap_reslices_into_new_created_at_window(self, MockSession: Any) -> None:
        session = MockSession.return_value
        items = [{"id": str(i), "createdAt": "2026-01-02T00:00:00Z"} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(items, has_next=True), _response([{"id": "in-window"}])])

        window_ms = int(datetime(2026, 1, 2, tzinfo=UTC).timestamp() * 1000)
        manager = _FakeManager()
        with mock.patch(f"{OPSGENIE_MODULE}.MAX_SEARCH_RESULTS", PAGE_SIZE):
            rows = _rows(_source("alerts", manager))

        # The offset resets and the query re-anchors on the last row's createdAt instead of
        # truncating at the 20,000-result cap.
        assert len(rows) == PAGE_SIZE + 1
        assert params[1]["offset"] == 0
        assert params[1]["query"] == f"createdAt >= {window_ms}"
        assert manager.saved_states[-1].offset == 0
        assert manager.saved_states[-1].window_start_ms == window_ms

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_search_cap_stops_when_window_cannot_advance(self, MockSession: Any) -> None:
        session = MockSession.return_value
        window_ms = int(datetime(2026, 1, 2, tzinfo=UTC).timestamp() * 1000)
        items = [{"id": str(i), "createdAt": "2026-01-02T00:00:00Z"} for i in range(PAGE_SIZE)]
        _wire(session, [_response(items, has_next=True)])

        manager = _FakeManager(resume_state=OpsgenieResumeConfig(offset=0, window_start_ms=window_ms))
        with mock.patch(f"{OPSGENIE_MODULE}.MAX_SEARCH_RESULTS", PAGE_SIZE):
            rows = _rows(_source("alerts", manager))

        # Every row shares the current window's createdAt, so re-slicing would loop on the same
        # page forever — the iterator yields what it has and stops instead.
        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_on_429_then_succeeds(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(429), _response([{"id": "1"}])])

        with mock.patch.object(RESTClient._send_request.retry, "sleep"):  # type: ignore[attr-defined]
            rows = _rows(_source("alerts", _FakeManager()))

        assert rows == [{"id": "1"}]
        assert session.send.call_count == 2


class TestValidateCredentials:
    def _patch_session(self, get_side_effect: Any) -> Any:
        session = mock.MagicMock()
        session.get.side_effect = get_side_effect
        return mock.patch(f"{OPSGENIE_MODULE}.make_tracked_session", return_value=session), session

    def _mock_response(self, status_code: int, body: Any = None, text: str = "") -> mock.MagicMock:
        response = mock.MagicMock()
        response.status_code = status_code
        response.text = text
        response.json.return_value = body if body is not None else {}
        return response

    @pytest.mark.parametrize(
        "status_code,expected_ok,expected_status",
        [
            (200, True, 200),
            (401, False, 401),
            (403, False, 403),
            (422, False, 422),
            (500, False, 500),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool, expected_status: int) -> None:
        ctx, _ = self._patch_session([self._mock_response(status_code, body={}, text="boom")])
        with ctx:
            ok, status, _error = validate_credentials("key", "us")
        assert ok is expected_ok
        assert status == expected_status

    def test_transport_failure_returns_zero_status(self) -> None:
        ctx, _ = self._patch_session(requests.ConnectionError("no network"))
        with ctx:
            ok, status, error = validate_credentials("key", "us")
        assert ok is False
        assert status == 0
        assert error == "no network"

    def test_uses_endpoint_path_when_schema_given(self) -> None:
        ctx, session = self._patch_session([self._mock_response(200)])
        with ctx:
            validate_credentials("key", "us", endpoint="incidents")
        assert session.get.call_args.args[0].startswith("https://api.opsgenie.com/v1/incidents?")

    @pytest.mark.parametrize(
        "region,expected_host",
        [
            ("us", "https://api.opsgenie.com"),
            ("eu", "https://api.eu.opsgenie.com"),
            ("unknown", "https://api.opsgenie.com"),
        ],
    )
    def test_region_selects_base_url(self, region: str, expected_host: str) -> None:
        ctx, session = self._patch_session([self._mock_response(200)])
        with ctx:
            validate_credentials("key", region)
        assert session.get.call_args.args[0].startswith(expected_host)


class TestOpsgenieSourceResponse:
    def test_alerts_partitioned_on_created_at(self) -> None:
        response = _source("alerts", _FakeManager())
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["createdAt"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    def test_unpartitioned_endpoint_has_no_partition_settings(self) -> None:
        response = _source("users", _FakeManager())
        assert response.primary_keys == ["id"]
        assert response.partition_keys is None
        assert response.partition_mode is None

    @pytest.mark.parametrize("endpoint", list(OPSGENIE_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = _source(endpoint, _FakeManager())
        assert response.name == endpoint
        assert response.primary_keys == [OPSGENIE_ENDPOINTS[endpoint].primary_key]
        assert callable(response.items)
