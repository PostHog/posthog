import json
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.drata import (
    REGION_BASE_URLS,
    DrataResumeConfig,
    base_url_for_region,
    drata_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.settings import DRATA_ENDPOINTS, ENDPOINTS

US_BASE_URL = REGION_BASE_URLS["US"]

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the drata module.
DRATA_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.drata.drata.make_tracked_session"
)
# The client backs off with tenacity between retries; neutralize the sleep so failure-path tests are fast.
SLEEP_PATCH = "tenacity.nap.time.sleep"

Route = Callable[[str, dict[str, Any]], Response]


def _resp(
    body: Any = None,
    *,
    status: int = 200,
    reason: str = "OK",
    url: Optional[str] = None,
    raw: Optional[bytes] = None,
) -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    if url is not None:
        resp.url = url
    resp._content = raw if raw is not None else json.dumps(body if body is not None else {}).encode()
    return resp


class _FakeManager:
    def __init__(self, state: DrataResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[DrataResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> DrataResumeConfig | None:
        return self._state

    def save_state(self, data: DrataResumeConfig) -> None:
        self.saved.append(data)


def _wire(session: mock.MagicMock, route: Route) -> list[dict[str, Any]]:
    """Wire a mock session to a URL+params router, snapshotting each request AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages (the paginator injects the cursor),
    so a copy must be taken when each request is prepared rather than read after the run.
    """
    session.headers = {}
    calls: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshot = {"url": request.url, "params": dict(request.params or {})}
        calls.append(snapshot)
        prepared = mock.MagicMock()
        prepared.url = request.url
        prepared.params = snapshot["params"]
        return prepared

    def _send(prepared: Any, **kwargs: Any) -> Response:
        return route(prepared.url, prepared.params)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return calls


def _run(
    mock_session: mock.MagicMock,
    route: Route,
    endpoint: str,
    manager: _FakeManager,
    region: str = "US",
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    session = mock_session.return_value
    calls = _wire(session, route)
    source = drata_source(
        api_key="drata_key",
        region=region,
        endpoint=endpoint,
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    )
    rows = [row for page in cast("Iterable[Any]", source.items()) for row in page]
    return rows, calls


class TestTopLevelCursorPagination:
    def _pages(self, url: str, params: dict[str, Any]) -> Response:
        cursor = params.get("cursor")
        if cursor is None:
            return _resp({"data": [{"id": 1}], "pagination": {"cursor": "c2", "totalCount": 2}})
        if cursor == "c2":
            return _resp({"data": [{"id": 2}], "pagination": {"cursor": None, "totalCount": 2}})
        raise AssertionError(f"unexpected cursor {cursor}")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_until_absent(self, mock_session: mock.MagicMock) -> None:
        manager = _FakeManager()
        rows, calls = _run(mock_session, self._pages, "users", manager)
        assert rows == [{"id": 1}, {"id": 2}]
        assert calls[0]["params"] == {"sort": "createdAt", "sortDir": "ASC", "size": 250}
        assert calls[1]["params"]["cursor"] == "c2"
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        assert [s.cursor for s in manager.saved] == ["c2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_cursor_does_not_advance(self, mock_session: mock.MagicMock) -> None:
        # An API that echoes the same cursor back must terminate, not loop forever.
        def route(url: str, params: dict[str, Any]) -> Response:
            return _resp({"data": [{"id": 1}], "pagination": {"cursor": params.get("cursor") or "c1"}})

        manager = _FakeManager()
        rows, calls = _run(mock_session, route, "users", manager)
        assert [c["params"].get("cursor") for c in calls] == [None, "c1"]
        assert len(rows) == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, mock_session: mock.MagicMock) -> None:
        manager = _FakeManager(DrataResumeConfig(cursor="c2"))
        rows, calls = _run(mock_session, self._pages, "users", manager)
        # The first page must never be re-fetched on resume.
        assert rows == [{"id": 2}]
        assert calls[0]["params"]["cursor"] == "c2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, mock_session: mock.MagicMock) -> None:
        def route(url: str, params: dict[str, Any]) -> Response:
            return _resp({"data": [], "pagination": {"cursor": None}})

        manager = _FakeManager()
        rows, _ = _run(mock_session, route, "users", manager)
        assert rows == []
        assert manager.saved == []

    @parameterized.expand([("US",), ("EU",), ("APAC",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_requests_hit_the_selected_region_host(self, region: str, mock_session: mock.MagicMock) -> None:
        manager = _FakeManager()
        _, calls = _run(mock_session, lambda url, params: _resp({"data": []}), "users", manager, region=region)
        assert calls[0]["url"] == f"{REGION_BASE_URLS[region]}/users"


class TestEventsIncremental:
    def _pages(self, url: str, params: dict[str, Any]) -> Response:
        cursor = params.get("cursor")
        if cursor is None:
            return _resp({"data": [{"id": "e1"}], "pagination": {"cursor": "c2"}})
        return _resp({"data": [{"id": "e2"}], "pagination": {"cursor": None}})

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_server_side_filter_sent_on_every_page(self, mock_session: mock.MagicMock) -> None:
        manager = _FakeManager()
        _, calls = _run(
            mock_session,
            self._pages,
            "events",
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            incremental_field="createdAt",
        )
        assert len(calls) == 2
        for call in calls:
            assert call["params"]["createdAtStartDate"] == "2026-01-02T03:04:05.000Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_date_watermark_formatted_as_utc_datetime(self, mock_session: mock.MagicMock) -> None:
        manager = _FakeManager()
        _, calls = _run(
            mock_session,
            self._pages,
            "events",
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 1, 2),
            incremental_field="createdAt",
        )
        assert calls[0]["params"]["createdAtStartDate"] == "2026-01-02T00:00:00.000Z"

    def test_unknown_incremental_field_raises(self) -> None:
        with pytest.raises(ValueError, match="no server-side filter"):
            drata_source(
                api_key="drata_key",
                region="US",
                endpoint="events",
                resumable_source_manager=_FakeManager(),  # type: ignore[arg-type]
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-01-01",
                incremental_field="updatedAt",
            )

    @parameterized.expand(
        [
            ("incremental_disabled", False, "2026-01-01"),
            ("no_last_value", True, None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_param_without_watermark(
        self, _name: str, should_use: bool, last_value: Any, mock_session: mock.MagicMock
    ) -> None:
        manager = _FakeManager()
        _, calls = _run(
            mock_session,
            self._pages,
            "events",
            manager,
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=last_value,
            incremental_field="createdAt",
        )
        assert "createdAtStartDate" not in calls[0]["params"]


class TestWorkspaceFanOut:
    def _pages(self, url: str, params: dict[str, Any]) -> Response:
        if url.endswith("/workspaces"):
            return _resp({"data": [{"id": 10}, {"id": 20}], "pagination": {"cursor": None}})
        if url.endswith("/workspaces/10/controls"):
            if params.get("cursor") is None:
                return _resp({"data": [{"id": 1}], "pagination": {"cursor": "w10c2"}})
            return _resp({"data": [{"id": 2}], "pagination": {"cursor": None}})
        if url.endswith("/workspaces/20/controls"):
            return _resp({"data": [{"id": 1}], "pagination": {"cursor": None}})
        raise AssertionError(f"unexpected url {url}")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_every_workspace_and_injects_workspace_id(self, mock_session: mock.MagicMock) -> None:
        rows, _ = _run(mock_session, self._pages, "controls", _FakeManager())
        # Control id 1 appears in both workspaces; the injected workspaceId keeps the
        # ["workspaceId", "id"] primary key unique table-wide.
        assert rows == [
            {"id": 1, "workspaceId": 10},
            {"id": 2, "workspaceId": 10},
            {"id": 1, "workspaceId": 20},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_cursor_within_parent_and_marks_parents_complete(self, mock_session: mock.MagicMock) -> None:
        manager = _FakeManager()
        _run(mock_session, self._pages, "controls", manager)
        states = [s.fanout_state for s in manager.saved]
        # Fan-out checkpoints key each parent by its resolved child PATH (relative to the base URL).
        ws10 = "/workspaces/10/controls"
        ws20 = "/workspaces/20/controls"
        # Workspace 10's in-progress cursor is checkpointed under its child path.
        assert any(s and s.get("current") == ws10 and s.get("child_state") == {"cursor": "w10c2"} for s in states)
        # Both workspaces are eventually recorded complete so a restart skips them.
        assert any(s and set(s.get("completed") or []) >= {ws10, ws20} for s in states)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_completed_parent_without_refetching_it(self, mock_session: mock.MagicMock) -> None:
        manager = _FakeManager(
            DrataResumeConfig(
                fanout_state={
                    "completed": ["/workspaces/10/controls"],
                    "current": None,
                    "child_state": None,
                }
            )
        )
        rows, calls = _run(mock_session, self._pages, "controls", manager)
        assert rows == [{"id": 1, "workspaceId": 20}]
        child_urls = [c["url"] for c in calls if "/controls" in c["url"]]
        assert child_urls == [f"{US_BASE_URL}/workspaces/20/controls"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_cursor_applies_to_in_progress_parent_only(self, mock_session: mock.MagicMock) -> None:
        manager = _FakeManager(
            DrataResumeConfig(
                fanout_state={
                    "completed": [],
                    "current": "/workspaces/10/controls",
                    "child_state": {"cursor": "w10c2"},
                }
            )
        )
        rows, calls = _run(mock_session, self._pages, "controls", manager)
        # Workspace 10 resumes mid-pagination; workspace 20 starts from its first page.
        assert rows == [{"id": 2, "workspaceId": 10}, {"id": 1, "workspaceId": 20}]
        first_child_call = next(c for c in calls if c["url"].endswith("/workspaces/10/controls"))
        assert first_child_call["params"]["cursor"] == "w10c2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_deleted_bookmark_parent_starts_over(self, mock_session: mock.MagicMock) -> None:
        manager = _FakeManager(
            DrataResumeConfig(
                fanout_state={
                    "completed": ["/workspaces/999/controls"],
                    "current": None,
                    "child_state": None,
                }
            )
        )
        rows, _ = _run(mock_session, self._pages, "controls", manager)
        assert len(rows) == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_resume_state_starts_fresh(self, mock_session: mock.MagicMock) -> None:
        # Pre-migration saved state carried (cursor, parent_id) but no fanout_state; it must still
        # parse and simply restart the fan-out.
        manager = _FakeManager(DrataResumeConfig(cursor="stale", parent_id=10))
        rows, _ = _run(mock_session, self._pages, "controls", manager)
        assert len(rows) == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_parent_404_is_skipped_and_sync_continues(self, mock_session: mock.MagicMock) -> None:
        def route(url: str, params: dict[str, Any]) -> Response:
            if url.endswith("/workspaces"):
                return _resp({"data": [{"id": 10}, {"id": 20}], "pagination": {"cursor": None}})
            if url.endswith("/workspaces/10/controls"):
                return _resp({}, status=404, reason="Not Found", url=url)
            return _resp({"data": [{"id": 1}], "pagination": {"cursor": None}})

        rows, _ = _run(mock_session, route, "controls", _FakeManager())
        assert rows == [{"id": 1, "workspaceId": 20}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_parent_403_fails_the_sync(self, mock_session: mock.MagicMock) -> None:
        def route(url: str, params: dict[str, Any]) -> Response:
            if url.endswith("/workspaces"):
                return _resp({"data": [{"id": 10}], "pagination": {"cursor": None}})
            return _resp({}, status=403, reason="Forbidden", url=url)

        with pytest.raises(requests.HTTPError):
            _run(mock_session, route, "controls", _FakeManager())

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_risks_fan_out_over_risk_registers(self, mock_session: mock.MagicMock) -> None:
        def route(url: str, params: dict[str, Any]) -> Response:
            if url.endswith("/risk-registers"):
                return _resp({"data": [{"id": 5}], "pagination": {"cursor": None}})
            if url.endswith("/risk-registers/5/risks"):
                return _resp({"data": [{"id": 1, "riskId": "RISK-001"}], "pagination": {"cursor": None}})
            raise AssertionError(f"unexpected url {url}")

        rows, _ = _run(mock_session, route, "risks", _FakeManager())
        assert rows == [{"id": 1, "riskId": "RISK-001", "riskRegisterId": 5}]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_raise_retryable_error(
        self, _name: str, status: int, mock_session: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        def route(url: str, params: dict[str, Any]) -> Response:
            return _resp({}, status=status, reason="Server Error", url=url)

        with pytest.raises(RESTClientRetryableError):
            _run(mock_session, route, "users", _FakeManager())

    @parameterized.expand(
        [
            ("unauthorized", 401, "Unauthorized"),
            ("forbidden", 403, "Forbidden"),
            ("terms", 412, "Precondition Failed"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error_matchable_by_host_prefix(
        self, _name: str, status: int, reason: str, mock_session: mock.MagicMock
    ) -> None:
        request_url = f"{US_BASE_URL}/users?cursor=abc&size=250"

        def route(url: str, params: dict[str, Any]) -> Response:
            return _resp({}, status=status, reason=reason, url=request_url)

        with pytest.raises(requests.HTTPError) as exc_info:
            _run(mock_session, route, "users", _FakeManager())
        # The base host prefix stays intact so `get_non_retryable_errors()` can still match it.
        assert "for url: https://public-api" in str(exc_info.value)

    @parameterized.expand(
        [
            ("bare_list", b'[{"id": 1}]'),
            ("missing_data", b'{"pagination": {}}'),
            ("data_is_object", b'{"data": {"id": 1}}'),
        ]
    )
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_payload_is_retryable(
        self, _name: str, raw: bytes, mock_session: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        def route(url: str, params: dict[str, Any]) -> Response:
            return _resp(raw=raw, url=url)

        with pytest.raises(RESTClientRetryableError):
            _run(mock_session, route, "users", _FakeManager())


class TestCredentialValidation:
    def _session(self, response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    def _http(self, status: int) -> mock.MagicMock:
        response = mock.MagicMock()
        response.status_code = status
        return response

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Drata API key"),
            # A genuine token without the workspaces read scope must not block source creation —
            # custom-scoped keys may only grant the endpoints the user wants to sync.
            ("forbidden_scope", 403, True, None),
            (
                "terms_not_accepted",
                412,
                False,
                "You must accept the Drata API terms and conditions in your Drata account before connecting",
            ),
            ("server_error", 500, False, "Drata returned HTTP 500"),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        with mock.patch(DRATA_SESSION_PATCH, return_value=self._session(self._http(status))):
            assert validate_credentials("drata_key", "US") == (expected_valid, expected_message)

    def test_connection_error_reports_message(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with mock.patch(DRATA_SESSION_PATCH, return_value=session):
            valid, message = validate_credentials("drata_key", "US")
        assert valid is False
        assert message is not None

    def test_probe_targets_the_selected_region(self) -> None:
        session = self._session(self._http(200))
        with mock.patch(DRATA_SESSION_PATCH, return_value=session):
            validate_credentials("drata_key", "EU")
        url = session.get.call_args.args[0]
        assert url.startswith(f"{REGION_BASE_URLS['EU']}/workspaces")

    @parameterized.expand(
        [("lowercase", "eu", "EU"), ("unknown_falls_back_to_us", "atlantis", "US"), ("none", None, "US")]
    )
    def test_base_url_for_region_normalizes(self, _name: str, region: str | None, expected: str) -> None:
        assert base_url_for_region(region) == REGION_BASE_URLS[expected]


class TestDrataSourceResponse:
    def _response(self, endpoint: str):
        return drata_source(
            api_key="drata_key",
            region="US",
            endpoint=endpoint,
            resumable_source_manager=_FakeManager(),  # type: ignore[arg-type]
        )

    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_primary_keys_match_endpoint_config(self, endpoint: str) -> None:
        response = self._response(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == DRATA_ENDPOINTS[endpoint].primary_keys

    @parameterized.expand([("controls",), ("monitoring_tests",), ("evidence_library",), ("frameworks",)])
    def test_workspace_children_use_composite_primary_key(self, endpoint: str) -> None:
        # Child ids aren't documented as unique beyond their workspace; a bare ["id"] key would
        # multi-match on merge and duplicate rows across workspaces.
        assert self._response(endpoint).primary_keys == ["workspaceId", "id"]

    def test_events_partitions_on_stable_created_at_and_defers_watermark(self) -> None:
        response = self._response("events")
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]
        # The requested ASC ordering couldn't be verified against a live account, so the watermark
        # must only commit after a complete sync.
        assert response.sort_mode == "desc"

    @parameterized.expand([(e,) for e in ENDPOINTS if e != "events"])
    def test_full_refresh_endpoints_declare_asc(self, endpoint: str) -> None:
        assert self._response(endpoint).sort_mode == "asc"
