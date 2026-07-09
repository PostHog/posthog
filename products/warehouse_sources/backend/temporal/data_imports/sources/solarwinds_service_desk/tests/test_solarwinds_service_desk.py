from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk import (
    solarwinds_service_desk,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.settings import (
    ENDPOINTS,
    PER_PAGE,
    SOLARWINDS_SERVICE_DESK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.solarwinds_service_desk import (
    SolarwindsServiceDeskResumeConfig,
    SolarwindsServiceDeskRetryableError,
    _format_updated_from,
    _headers,
    _unwrap_rows,
    base_url,
    check_access,
    get_rows,
    solarwinds_service_desk_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = solarwinds_service_desk._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: SolarwindsServiceDeskResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SolarwindsServiceDeskResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SolarwindsServiceDeskResumeConfig | None:
        return self._state

    def save_state(self, data: SolarwindsServiceDeskResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        pages: Mapping[str, tuple[list[Any], int | None]],
        endpoint: str = "incidents",
        **kwargs: Any,
    ) -> tuple[list[dict], list[str]]:
        requested_urls: list[str] = []

        def fake_fetch(session: Any, url: str, logger: Any) -> tuple[list[Any], int | None]:
            requested_urls.append(url)
            return pages[url]

        rows: list[dict] = []
        with (
            patch.object(solarwinds_service_desk, "_fetch_page", fake_fetch),
            patch.object(solarwinds_service_desk, "make_tracked_session", return_value=MagicMock()),
        ):
            for batch in get_rows(
                region="us",
                api_token="swsd-token",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
                **kwargs,
            ):
                rows.extend(batch)
        return rows, requested_urls

    @staticmethod
    def _url(endpoint: str, page: int, updated_from: str | None = None, host: str = "https://api.samanage.com") -> str:
        path = SOLARWINDS_SERVICE_DESK_ENDPOINTS[endpoint].path
        base = f"{host}{path}?per_page={PER_PAGE}&page={page}"
        if updated_from is not None:
            return f"{base}&updated_from={updated_from.replace(':', '%3A')}"
        return base

    def test_stops_after_last_page_per_total_pages_header(self) -> None:
        manager = _FakeResumableManager()
        pages = {
            self._url("incidents", 1): ([{"id": 1}], 2),
            self._url("incidents", 2): ([{"id": 2}], 2),
        }
        rows, urls = self._collect(manager, pages)
        assert rows == [{"id": 1}, {"id": 2}]
        assert len(urls) == 2
        # State is saved after each yielded page, pointing at the next page to fetch.
        assert [s.next_page for s in manager.saved] == [2]

    def test_short_page_does_not_stop_pagination(self) -> None:
        # A page smaller than PER_PAGE must not be treated as the end: the server may clamp
        # `per_page`, so only an empty page or the X-Total-Pages header terminates the crawl.
        manager = _FakeResumableManager()
        pages: Mapping[str, tuple[list[Any], int | None]] = {
            self._url("incidents", 1): ([{"id": 1}], None),
            self._url("incidents", 2): ([{"id": 2}], None),
            self._url("incidents", 3): ([], None),
        }
        rows, urls = self._collect(manager, pages)
        assert rows == [{"id": 1}, {"id": 2}]
        assert len(urls) == 3

    def test_resumes_from_saved_page_with_saved_filter(self) -> None:
        manager = _FakeResumableManager(SolarwindsServiceDeskResumeConfig(next_page=3, updated_from="2026-01-01T00:00"))
        pages = {self._url("incidents", 3, "2026-01-01T00:00"): ([{"id": 9}], 3)}
        rows, urls = self._collect(
            manager,
            pages,
            # A resumed run must reuse the persisted filter, not recompute one from this watermark.
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-02-02T00:00:00Z",
        )
        assert rows == [{"id": 9}]
        assert urls == [self._url("incidents", 3, "2026-01-01T00:00")]

    def test_incremental_watermark_adds_updated_from_param(self) -> None:
        manager = _FakeResumableManager()
        pages: Mapping[str, tuple[list[Any], int | None]] = {self._url("incidents", 1, "2026-01-05T08:30"): ([], None)}
        _, urls = self._collect(
            manager,
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 5, 8, 30, tzinfo=UTC),
        )
        assert urls == [self._url("incidents", 1, "2026-01-05T08:30")]

    @parameterized.expand(
        [
            ("full_refresh_endpoint", "users", True, datetime(2026, 1, 5, tzinfo=UTC)),
            ("incremental_disabled", "incidents", False, datetime(2026, 1, 5, tzinfo=UTC)),
            ("no_watermark", "incidents", True, None),
            ("unparseable_watermark", "incidents", True, "not a datetime"),
        ]
    )
    def test_no_updated_from_param(self, _name: str, endpoint: str, use_incremental: bool, watermark: Any) -> None:
        manager = _FakeResumableManager()
        pages: Mapping[str, tuple[list[Any], int | None]] = {self._url(endpoint, 1): ([], None)}
        _, urls = self._collect(
            manager,
            pages,
            endpoint=endpoint,
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value=watermark,
        )
        assert urls == [self._url(endpoint, 1)]

    def test_wrapped_rows_are_unwrapped(self) -> None:
        manager = _FakeResumableManager()
        pages = {self._url("problems", 1): ([{"problem": {"id": 7, "name": "P"}}], 1)}
        rows, _ = self._collect(manager, pages, endpoint="problems")
        assert rows == [{"id": 7, "name": "P"}]


class TestFormatUpdatedFrom:
    @parameterized.expand(
        [
            ("aware_utc", datetime(2026, 1, 5, 8, 30, 59, tzinfo=UTC), "2026-01-05T08:30"),
            ("aware_offset", datetime(2026, 1, 5, 9, 30, tzinfo=timezone(timedelta(hours=1))), "2026-01-05T08:30"),
            ("naive_treated_as_utc", datetime(2026, 1, 5, 8, 30), "2026-01-05T08:30"),
            ("iso_string", "2026-01-05T08:30:59.000+00:00", "2026-01-05T08:30"),
            ("date", date(2026, 1, 5), "2026-01-05T00:00"),
            ("garbage_string", "not a datetime", None),
            ("integer", 12345, None),
            ("none", None, None),
        ]
    )
    def test_formats(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_updated_from(value) == expected


class TestUnwrapRows:
    def test_handles_both_documented_list_shapes(self) -> None:
        # The official response samples show bare records on some endpoints and singularly wrapped
        # records on others — both must normalize to the bare record.
        items = [
            {"user": {"id": 1, "name": "A"}},
            {"id": 2, "name": "B"},
            {"user": "not a record", "id": 3},
            "junk",
        ]
        assert _unwrap_rows(items, "user") == [
            {"id": 1, "name": "A"},
            {"id": 2, "name": "B"},
            {"user": "not a record", "id": 3},
        ]


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None, headers: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else []
        response.headers = headers or {}
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(SolarwindsServiceDeskRetryableError):
            _fetch_page_unwrapped(session, "https://api.samanage.com/incidents.json", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "https://api.samanage.com/incidents.json", MagicMock())

    def test_non_list_body_is_retryable(self) -> None:
        session = self._session_returning(200, {"error": "weird"})
        with pytest.raises(SolarwindsServiceDeskRetryableError):
            _fetch_page_unwrapped(session, "https://api.samanage.com/incidents.json", MagicMock())

    @parameterized.expand(
        [
            ("header_present", {"X-Total-Pages": "7"}, 7),
            ("header_missing", {}, None),
            ("header_garbage", {"X-Total-Pages": "lots"}, None),
        ]
    )
    def test_total_pages_header_parsing(self, _name: str, headers: dict, expected: int | None) -> None:
        session = self._session_returning(200, [{"id": 1}], headers)
        items, total_pages = _fetch_page_unwrapped(session, "https://api.samanage.com/incidents.json", MagicMock())
        assert items == [{"id": 1}]
        assert total_pages == expected


class TestAuthAndHosts:
    def test_headers_carry_vendor_auth_and_versioned_accept(self) -> None:
        # The versioned Accept header is mandatory — without it the API can serve legacy payloads.
        headers = _headers("swsd-token")
        assert headers["X-Samanage-Authorization"] == "Bearer swsd-token"
        assert headers["Accept"] == "application/vnd.samanage.v2.1+json"

    @parameterized.expand(
        [
            ("us", "https://api.samanage.com"),
            ("eu", "https://apieu.samanage.com"),
            ("au", "https://apiau.samanage.com"),
            (None, "https://api.samanage.com"),
            ("unknown", "https://api.samanage.com"),
        ]
    )
    def test_base_url_per_region(self, region: str | None, expected: str) -> None:
        assert base_url(region) == expected


class TestCheckAccess:
    @staticmethod
    def _session(response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "SolarWinds Service Desk returned HTTP 500"),
        ]
    )
    @patch(f"{solarwinds_service_desk.__name__}.make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        mock_session.return_value = self._session(response)
        assert check_access("us", "swsd-token") == (expected_status, expected_message)

    @patch(f"{solarwinds_service_desk.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("us", "swsd-token")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok_at_create", 200, None, True, None),
            ("bad_token_at_create", 401, None, False, "Invalid SolarWinds Service Desk API token"),
            # A 403 with a genuine token must not block source-create, but must fail a
            # schema-scoped probe so the user sees which table their role can't read.
            ("forbidden_at_create", 403, None, True, None),
            (
                "forbidden_for_schema",
                403,
                "/incidents.json",
                False,
                "Your SolarWinds Service Desk token does not have permission to read this resource",
            ),
            ("server_error", 500, None, False, "SolarWinds Service Desk returned HTTP 500"),
        ]
    )
    @patch(f"{solarwinds_service_desk.__name__}.make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        path: str | None,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_session.return_value = self._session(response)
        assert validate_credentials("us", "swsd-token", path) == (expected_valid, expected_message)


class TestSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        config = SOLARWINDS_SERVICE_DESK_ENDPOINTS[endpoint]
        response = solarwinds_service_desk_source(
            region="us",
            api_token="swsd-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Ordering is undocumented, so the watermark must only commit after a completed sync.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    def test_partition_keys_are_stable_creation_fields(self) -> None:
        # updated_at-style partition keys rewrite partitions on every sync.
        assert all(
            config.partition_key in (None, "created_at") for config in SOLARWINDS_SERVICE_DESK_ENDPOINTS.values()
        )
        assert set(SOLARWINDS_SERVICE_DESK_ENDPOINTS) == set(ENDPOINTS)
