from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner import hubplanner
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.hubplanner import (
    PAGE_SIZE,
    HubPlannerResumeConfig,
    _build_request_plan,
    _format_value,
    _get_headers,
    get_rows,
    hubplanner_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.settings import HUBPLANNER_ENDPOINTS


class TestFormatValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (
                "datetime_microseconds_truncated_to_millis",
                datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T10:30:45.123Z",
            ),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "5b1977ade02d407011112222", "5b1977ade02d407011112222"),
        ]
    )
    def test_format_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_value(value) == expected

    def test_datetime_has_no_plus_zero_offset(self) -> None:
        # Hub Planner expects a Z suffix, not the +00:00 offset isoformat() produces.
        assert "+00:00" not in _format_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestHeaders:
    def test_authorization_header_is_raw_key_without_bearer_prefix(self) -> None:
        headers = _get_headers("my-secret-key")
        assert headers["Authorization"] == "my-secret-key"
        assert "Bearer" not in headers["Authorization"]
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"


class TestBuildRequestPlan:
    def test_full_refresh_endpoint_uses_unsorted_get(self) -> None:
        # No `sort` on full-refresh GET: an unsupported sort field would 400 the whole sync.
        method, path, body, sort_field = _build_request_plan(
            HUBPLANNER_ENDPOINTS["projects"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert (method, path, body, sort_field) == ("GET", "/project", None, None)

    def test_incremental_endpoint_without_incremental_selected_uses_get(self) -> None:
        # A user syncing bookings via full refresh should hit the plain GET list, not search.
        method, path, body, sort_field = _build_request_plan(
            HUBPLANNER_ENDPOINTS["bookings"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert method == "GET"
        assert path == "/booking"
        assert body is None

    def test_incremental_first_sync_posts_search_with_empty_body(self) -> None:
        # should_use_incremental_field=True but no stored watermark yet: fetch everything, sorted asc.
        method, path, body, sort_field = _build_request_plan(
            HUBPLANNER_ENDPOINTS["bookings"], should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert (method, path, body, sort_field) == ("POST", "/booking/search", {}, "updatedDate")

    def test_incremental_with_watermark_filters_on_updated_date(self) -> None:
        method, path, body, sort_field = _build_request_plan(
            HUBPLANNER_ENDPOINTS["time_entries"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert method == "POST"
        assert path == "/timeentry/search"
        assert body == {"updatedDate": {"$gte": "2026-03-04T02:58:14.000Z"}}
        assert sort_field == "updatedDate"

    def test_search_only_endpoint_lists_via_search(self) -> None:
        # Milestones have no GET-all endpoint, so full refresh still POSTs to /milestone/search.
        method, path, body, sort_field = _build_request_plan(
            HUBPLANNER_ENDPOINTS["milestones"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert (method, path, body, sort_field) == ("POST", "/milestone/search", {}, None)


class _FakeResumableManager:
    def __init__(self, state: Optional[HubPlannerResumeConfig] = None) -> None:
        self._state = state
        self.saved: list[HubPlannerResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> Optional[HubPlannerResumeConfig]:
        return self._state

    def save_state(self, data: HubPlannerResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _run(manager: _FakeResumableManager, pages: list[list[dict]], **kwargs: Any) -> tuple[list[list[dict]], list]:
        calls: list[dict[str, Any]] = []

        def fake_fetch(session: Any, method: str, url: str, headers: dict, body: Any, logger: Any) -> list[dict]:
            calls.append({"method": method, "url": url, "body": body})
            return pages[len(calls) - 1]

        with (
            patch.object(hubplanner, "_fetch_page", fake_fetch),
            patch.object(hubplanner, "make_tracked_session", return_value=MagicMock()),
        ):
            batches = list(
                get_rows(
                    api_key="k",
                    endpoint=kwargs.pop("endpoint", "projects"),
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    **kwargs,
                )  # type: ignore[arg-type]
            )
        return batches, calls

    def test_single_short_page_terminates_without_saving_state(self) -> None:
        manager = _FakeResumableManager()
        batches, calls = self._run(manager, pages=[[{"_id": "1"}, {"_id": "2"}]])

        assert batches == [[{"_id": "1"}, {"_id": "2"}]]
        assert len(calls) == 1
        # A short first page is the last page, so there's no next page to checkpoint.
        assert manager.saved == []

    def test_paginates_until_short_page_and_saves_state_after_each_full_page(self) -> None:
        manager = _FakeResumableManager()
        full_page = [{"_id": str(i)} for i in range(PAGE_SIZE)]
        short_page = [{"_id": "last"}]
        batches, calls = self._run(manager, pages=[full_page, short_page])

        assert batches == [full_page, short_page]
        assert [c["url"].split("page=")[1].split("&")[0] for c in calls] == ["0", "1"]
        # State saved once after the first (full) page points at page 1; the short page ends the loop.
        assert manager.saved == [HubPlannerResumeConfig(page=1)]

    def test_resumes_from_saved_page(self) -> None:
        manager = _FakeResumableManager(state=HubPlannerResumeConfig(page=3))
        _batches, calls = self._run(manager, pages=[[{"_id": "x"}]])

        assert calls[0]["url"].split("page=")[1].split("&")[0] == "3"

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = _FakeResumableManager()
        batches, calls = self._run(manager, pages=[[]])
        assert batches == []
        assert len(calls) == 1

    def test_incremental_sync_posts_search_body(self) -> None:
        manager = _FakeResumableManager()
        _batches, calls = self._run(
            manager,
            pages=[[{"_id": "1"}]],
            endpoint="bookings",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert calls[0]["method"] == "POST"
        assert "/booking/search" in calls[0]["url"]
        assert calls[0]["body"] == {"updatedDate": {"$gte": "2026-03-04T00:00:00.000Z"}}


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_retryable_error(self, _name: str, status_code: int) -> None:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        session = MagicMock()
        session.request.return_value = response

        with patch.object(hubplanner._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(hubplanner.HubPlannerRetryableError):
                hubplanner._fetch_page(session, "GET", "https://api.hubplanner.com/v1/project", {}, None, MagicMock())

        assert session.request.call_count == 5

    def test_bare_list_response_returned_as_is(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = [{"_id": "1"}, {"_id": "2"}]
        session = MagicMock()
        session.request.return_value = response

        result = hubplanner._fetch_page(session, "GET", "https://api.hubplanner.com/v1/project", {}, None, MagicMock())
        assert result == [{"_id": "1"}, {"_id": "2"}]

    def test_non_list_response_returns_empty(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = {"message": "unexpected"}
        session = MagicMock()
        session.request.return_value = response

        result = hubplanner._fetch_page(session, "GET", "https://api.hubplanner.com/v1/project", {}, None, MagicMock())
        assert result == []

    def test_auth_error_does_not_log_response_body(self) -> None:
        # Hub Planner echoes the API key back in auth-error bodies; logging it would leak the secret.
        response = requests.Response()
        response.status_code = 403
        response._content = b'{"error":"OAUTH_ERROR_TOKEN_NOT_VALID","authHeaders":"my-secret-key"}'
        session = MagicMock()
        session.request.return_value = response
        logger = MagicMock()

        with pytest.raises(requests.HTTPError):
            hubplanner._fetch_page(session, "GET", "https://api.hubplanner.com/v1/project", {}, None, logger)

        logged = " ".join(str(call) for call in logger.error.call_args_list)
        assert "my-secret-key" not in logged
        assert "OAUTH_ERROR_TOKEN_NOT_VALID" not in logged


class TestSourceResponse:
    def test_partitioned_endpoint_sets_datetime_partitioning(self) -> None:
        response = hubplanner_source(
            api_key="k", endpoint="bookings", logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.name == "bookings"
        assert response.primary_keys == ["_id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdDate"]
        assert response.sort_mode == "asc"

    def test_endpoint_without_partition_key_has_no_partitioning(self) -> None:
        # Vacations carry no creation timestamp, so they aren't partitioned.
        response = hubplanner_source(
            api_key="k", endpoint="vacations", logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("forbidden", 403, False), ("unauthorized", 401, False)])
    def test_status_maps_to_validity(self, _name: str, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response

        with patch.object(hubplanner, "make_tracked_session", return_value=session):
            assert validate_credentials("some-key") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(hubplanner, "make_tracked_session", return_value=session):
            assert validate_credentials("some-key") is False
