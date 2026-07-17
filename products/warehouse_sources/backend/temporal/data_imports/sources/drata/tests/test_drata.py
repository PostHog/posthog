from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.drata import drata
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.drata import (
    REGION_BASE_URLS,
    DrataResumeConfig,
    DrataRetryableError,
    base_url_for_region,
    check_access,
    drata_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.settings import DRATA_ENDPOINTS, ENDPOINTS

US_BASE_URL = REGION_BASE_URLS["US"]

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = drata._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: DrataResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[DrataResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> DrataResumeConfig | None:
        return self._state

    def save_state(self, data: DrataResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager,
    fake_fetch: Any,
    endpoint: str,
    region: str = "US",
    **kwargs: Any,
) -> tuple[list[dict], list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def _fetch(session: Any, url: str, params: dict[str, Any], logger: Any) -> dict[str, Any]:
        calls.append({"url": url, "params": params})
        return fake_fetch(url, params)

    with (
        patch.object(drata, "_fetch_page", _fetch),
        patch.object(drata, "make_tracked_session", return_value=MagicMock()),
    ):
        rows: list[dict] = []
        for batch in get_rows(
            api_key="drata_key",
            region=region,
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(batch)
    return rows, calls


class TestTopLevelCursorPagination:
    def _pages(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        cursor = params.get("cursor")
        if cursor is None:
            return {"data": [{"id": 1}], "pagination": {"cursor": "c2", "totalCount": 2}}
        if cursor == "c2":
            return {"data": [{"id": 2}], "pagination": {"cursor": None, "totalCount": 2}}
        raise AssertionError(f"unexpected cursor {cursor}")

    def test_follows_cursor_until_absent(self) -> None:
        manager = _FakeResumableManager()
        rows, calls = _collect(manager, self._pages, "users")
        assert rows == [{"id": 1}, {"id": 2}]
        assert calls[0]["params"] == {"sort": "createdAt", "sortDir": "ASC", "size": 250}
        assert calls[1]["params"]["cursor"] == "c2"
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        assert [s.cursor for s in manager.saved] == ["c2"]

    def test_stops_when_cursor_does_not_advance(self) -> None:
        # An API that echoes the same cursor back must terminate, not loop forever.
        manager = _FakeResumableManager()

        def pages(url: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"data": [{"id": 1}], "pagination": {"cursor": params.get("cursor") or "c1"}}

        rows, calls = _collect(manager, pages, "users")
        assert [c["params"].get("cursor") for c in calls] == [None, "c1"]
        assert len(rows) == 2

    def test_resumes_from_saved_cursor(self) -> None:
        manager = _FakeResumableManager(DrataResumeConfig(cursor="c2"))
        rows, calls = _collect(manager, self._pages, "users")
        # The first page must never be re-fetched on resume.
        assert rows == [{"id": 2}]
        assert calls[0]["params"]["cursor"] == "c2"

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = _FakeResumableManager()

        def pages(url: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"data": [], "pagination": {"cursor": None}}

        rows, _ = _collect(manager, pages, "users")
        assert rows == []
        assert manager.saved == []

    @parameterized.expand([("US",), ("EU",), ("APAC",)])
    def test_requests_hit_the_selected_region_host(self, region: str) -> None:
        manager = _FakeResumableManager()
        _, calls = _collect(manager, lambda url, params: {"data": []}, "users", region=region)
        assert calls[0]["url"] == f"{REGION_BASE_URLS[region]}/users"


class TestEventsIncremental:
    def _pages(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        cursor = params.get("cursor")
        if cursor is None:
            return {"data": [{"id": "e1"}], "pagination": {"cursor": "c2"}}
        return {"data": [{"id": "e2"}], "pagination": {"cursor": None}}

    def test_server_side_filter_sent_on_every_page(self) -> None:
        manager = _FakeResumableManager()
        _, calls = _collect(
            manager,
            self._pages,
            "events",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            incremental_field="createdAt",
        )
        for call in calls:
            assert call["params"]["createdAtStartDate"] == "2026-01-02T03:04:05.000Z"

    def test_date_watermark_formatted_as_utc_datetime(self) -> None:
        manager = _FakeResumableManager()
        _, calls = _collect(
            manager,
            self._pages,
            "events",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 1, 2),
            incremental_field="createdAt",
        )
        assert calls[0]["params"]["createdAtStartDate"] == "2026-01-02T00:00:00.000Z"

    def test_unknown_incremental_field_raises(self) -> None:
        manager = _FakeResumableManager()
        with pytest.raises(ValueError, match="no server-side filter"):
            _collect(
                manager,
                self._pages,
                "events",
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
    def test_no_filter_param_without_watermark(self, _name: str, should_use: bool, last_value: Any) -> None:
        manager = _FakeResumableManager()
        _, calls = _collect(
            manager,
            self._pages,
            "events",
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=last_value,
            incremental_field="createdAt",
        )
        assert "createdAtStartDate" not in calls[0]["params"]


class TestWorkspaceFanOut:
    def _pages(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        if url.endswith("/workspaces"):
            return {"data": [{"id": 10}, {"id": 20}], "pagination": {"cursor": None}}
        if url.endswith("/workspaces/10/controls"):
            if params.get("cursor") is None:
                return {"data": [{"id": 1}], "pagination": {"cursor": "w10c2"}}
            return {"data": [{"id": 2}], "pagination": {"cursor": None}}
        if url.endswith("/workspaces/20/controls"):
            return {"data": [{"id": 1}], "pagination": {"cursor": None}}
        raise AssertionError(f"unexpected url {url}")

    def test_walks_every_workspace_and_injects_workspace_id(self) -> None:
        manager = _FakeResumableManager()
        rows, _ = _collect(manager, self._pages, "controls")
        # Control id 1 appears in both workspaces; the injected workspaceId keeps the
        # ["workspaceId", "id"] primary key unique table-wide.
        assert rows == [
            {"id": 1, "workspaceId": 10},
            {"id": 2, "workspaceId": 10},
            {"id": 1, "workspaceId": 20},
        ]

    def test_saves_cursor_within_parent_and_bookmark_between_parents(self) -> None:
        manager = _FakeResumableManager()
        _collect(manager, self._pages, "controls")
        assert [(s.parent_id, s.cursor) for s in manager.saved] == [(10, "w10c2"), (20, None)]

    def test_resumes_from_parent_bookmark_without_refetching_earlier_parents(self) -> None:
        manager = _FakeResumableManager(DrataResumeConfig(cursor=None, parent_id=20))
        rows, calls = _collect(manager, self._pages, "controls")
        assert rows == [{"id": 1, "workspaceId": 20}]
        child_urls = [c["url"] for c in calls if "/controls" in c["url"]]
        assert child_urls == [f"{US_BASE_URL}/workspaces/20/controls"]

    def test_resume_cursor_applies_to_bookmarked_parent_only(self) -> None:
        manager = _FakeResumableManager(DrataResumeConfig(cursor="w10c2", parent_id=10))
        rows, calls = _collect(manager, self._pages, "controls")
        # Workspace 10 resumes mid-pagination; workspace 20 starts from its first page.
        assert rows == [{"id": 2, "workspaceId": 10}, {"id": 1, "workspaceId": 20}]
        first_child_call = next(c for c in calls if c["url"].endswith("/workspaces/10/controls"))
        assert first_child_call["params"]["cursor"] == "w10c2"

    def test_deleted_bookmark_parent_starts_over(self) -> None:
        manager = _FakeResumableManager(DrataResumeConfig(cursor="stale", parent_id=999))
        rows, _ = _collect(manager, self._pages, "controls")
        assert len(rows) == 3

    def test_parent_404_is_skipped_and_sync_continues(self) -> None:
        manager = _FakeResumableManager()
        response = MagicMock()
        response.status_code = 404

        def pages(url: str, params: dict[str, Any]) -> dict[str, Any]:
            if url.endswith("/workspaces"):
                return {"data": [{"id": 10}, {"id": 20}], "pagination": {"cursor": None}}
            if url.endswith("/workspaces/10/controls"):
                raise requests.HTTPError("404 Client Error", response=response)
            return {"data": [{"id": 1}], "pagination": {"cursor": None}}

        rows, _ = _collect(manager, pages, "controls")
        assert rows == [{"id": 1, "workspaceId": 20}]

    def test_parent_403_fails_the_sync(self) -> None:
        manager = _FakeResumableManager()
        response = MagicMock()
        response.status_code = 403

        def pages(url: str, params: dict[str, Any]) -> dict[str, Any]:
            if url.endswith("/workspaces"):
                return {"data": [{"id": 10}], "pagination": {"cursor": None}}
            raise requests.HTTPError("403 Client Error", response=response)

        with pytest.raises(requests.HTTPError):
            _collect(manager, pages, "controls")

    def test_risks_fan_out_over_risk_registers(self) -> None:
        manager = _FakeResumableManager()

        def pages(url: str, params: dict[str, Any]) -> dict[str, Any]:
            if url.endswith("/risk-registers"):
                return {"data": [{"id": 5}], "pagination": {"cursor": None}}
            if url.endswith("/risk-registers/5/risks"):
                return {"data": [{"id": 1, "riskId": "RISK-001"}], "pagination": {"cursor": None}}
            raise AssertionError(f"unexpected url {url}")

        rows, _ = _collect(manager, pages, "risks")
        assert rows == [{"id": 1, "riskId": "RISK-001", "riskRegisterId": 5}]


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.reason = "Unauthorized"
        # The error path must strip the query string before the URL reaches the exception message.
        response.url = f"{US_BASE_URL}/users?cursor=abc&size=250"
        response.json.return_value = body if body is not None else {"data": [], "pagination": {}}
        response.text = ""
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(DrataRetryableError):
            _fetch_page_unwrapped(session, f"{US_BASE_URL}/users", {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("terms_not_accepted", 412)])
    def test_client_errors_raise_http_error_with_scrubbed_url(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError) as exc_info:
            _fetch_page_unwrapped(session, f"{US_BASE_URL}/users", {}, MagicMock())
        # The base URL stays so `get_non_retryable_errors()` can match; the query string must not
        # reach the persisted error message.
        message = str(exc_info.value)
        assert f"for url: {US_BASE_URL}/users" in message
        assert "?" not in message

    @parameterized.expand([("bare_list", [{"id": 1}]), ("missing_data", {"pagination": {}})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(DrataRetryableError):
            _fetch_page_unwrapped(session, f"{US_BASE_URL}/users", {}, MagicMock())


class TestCredentialValidation:
    def _session(self, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    def _response(self, status: int) -> MagicMock:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
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
        with patch.object(drata, "make_tracked_session", return_value=self._session(self._response(status))):
            assert validate_credentials("drata_key", "US") == (expected_valid, expected_message)

    def test_connection_error_reports_message(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with patch.object(drata, "make_tracked_session", return_value=session):
            valid, message = validate_credentials("drata_key", "US")
        assert valid is False
        assert message is not None and "boom" in message

    def test_check_access_probes_the_selected_region(self) -> None:
        session = self._session(self._response(200))
        with patch.object(drata, "make_tracked_session", return_value=session):
            check_access("drata_key", "EU")
        url = session.get.call_args.args[0]
        assert url == f"{REGION_BASE_URLS['EU']}/workspaces"

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
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
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
