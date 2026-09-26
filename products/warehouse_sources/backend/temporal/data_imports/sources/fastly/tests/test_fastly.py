from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.fastly import fastly
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.fastly import (
    FASTLY_BASE_URL,
    FastlyResumeConfig,
    FastlyRetryableError,
    _active_version_number,
    _build_url,
    _ensure_service_id,
    _flatten_usage_metrics,
    _next_cursor,
    _next_page_url,
    _usage_metrics_window,
    fastly_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.settings import ENDPOINTS, FASTLY_ENDPOINTS


def _fake_response(payload: Any, next_url: str | None = None) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.links = {"next": {"url": next_url}} if next_url else {}
    return response


class _FakeResumableManager:
    def __init__(self, state: FastlyResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[FastlyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> FastlyResumeConfig | None:
        return self._state

    def save_state(self, data: FastlyResumeConfig) -> None:
        self.saved.append(data)


class TestBuildUrl:
    def test_no_params_returns_base(self) -> None:
        assert _build_url(f"{FASTLY_BASE_URL}/service", {}) == f"{FASTLY_BASE_URL}/service"

    def test_encodes_params(self) -> None:
        assert _build_url(f"{FASTLY_BASE_URL}/service", {"per_page": 100}) == f"{FASTLY_BASE_URL}/service?per_page=100"


class TestNextPageUrl:
    def test_reads_next_link(self) -> None:
        response = MagicMock()
        response.links = {"next": {"url": "https://api.fastly.com/service?page=2"}}
        assert _next_page_url(response) == "https://api.fastly.com/service?page=2"

    def test_no_next_link_returns_none(self) -> None:
        response = MagicMock()
        response.links = {}
        assert _next_page_url(response) is None


class TestEnsureServiceId:
    def test_injects_missing_service_id(self) -> None:
        assert _ensure_service_id({"name": "www"}, "SVC")["service_id"] == "SVC"

    def test_keeps_existing_service_id(self) -> None:
        assert _ensure_service_id({"service_id": "REAL"}, "SVC")["service_id"] == "REAL"


class TestActiveVersionNumber:
    @parameterized.expand(
        [
            # The active version is preferred, even when a higher (draft) version number exists.
            ("prefers_active", [{"number": 1, "active": True}, {"number": 2, "active": False}], 1),
            # With no active version, fall back to the highest version number.
            ("falls_back_to_highest", [{"number": 1, "active": False}, {"number": 3, "active": False}], 3),
            ("no_versions", [], None),
        ]
    )
    def test_active_version_number(self, _name: str, versions: list[dict], expected: int | None) -> None:
        session = MagicMock()
        with patch.object(fastly, "_fetch", return_value=_fake_response(versions)):
            assert _active_version_number(session, "SVC", {}, MagicMock()) == expected


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False)])
    def test_validate_credentials_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(fastly, "make_tracked_session", return_value=session):
            assert validate_credentials("token") is expected

    def test_validate_credentials_swallows_exceptions(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(fastly, "make_tracked_session", return_value=session):
            assert validate_credentials("token") is False


class TestTokenRedaction:
    # The token rides in the custom `Fastly-Key` header, which the transport's name-based scrubber
    # doesn't know about — both entry points must pass it as a redact value or it leaks into samples.
    def test_validate_credentials_redacts_token(self) -> None:
        make_session = MagicMock(return_value=MagicMock())
        with patch.object(fastly, "make_tracked_session", make_session):
            validate_credentials("secret-token")
        assert make_session.call_args.kwargs["redact_values"] == ("secret-token",)

    def test_get_rows_redacts_token(self) -> None:
        make_session = MagicMock(return_value=MagicMock())
        pages = {f"{FASTLY_BASE_URL}/current_user": {"id": "U1"}}

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
            return _fake_response(pages[url])

        with (
            patch.object(fastly, "_fetch", side_effect=fake_fetch),
            patch.object(fastly, "make_tracked_session", make_session),
        ):
            list(get_rows("secret-token", "current_user", MagicMock(), _FakeResumableManager()))  # type: ignore[arg-type]
        assert make_session.call_args.kwargs["redact_values"] == ("secret-token",)


class TestFetchRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_status_retries_then_succeeds(self, _name: str, status_code: int) -> None:
        bad = MagicMock()
        bad.status_code = status_code
        good = MagicMock()
        good.status_code = 200
        good.ok = True

        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(fastly._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = fastly._fetch(session, f"{FASTLY_BASE_URL}/service", {}, MagicMock())

        assert result is good
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
            ("chunked", requests.exceptions.ChunkedEncodingError("Connection broken")),
        ]
    )
    def test_transient_exceptions_retried(self, _name: str, exc: Exception) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True

        session = MagicMock()
        session.get.side_effect = [exc, good]

        with patch.object(fastly._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = fastly._fetch(session, f"{FASTLY_BASE_URL}/service", {}, MagicMock())

        assert result is good
        assert session.get.call_count == 2

    def test_retryable_reraised_after_exhausting_attempts(self) -> None:
        bad = MagicMock()
        bad.status_code = 503
        session = MagicMock()
        session.get.return_value = bad

        with patch.object(fastly._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(FastlyRetryableError):
                fastly._fetch(session, f"{FASTLY_BASE_URL}/service", {}, MagicMock())

        assert session.get.call_count == 5


def _collect(endpoint: str, manager: _FakeResumableManager, pages: dict[str, Any]) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
        payload = pages[url]
        if isinstance(payload, tuple):
            body, next_url = payload
            return _fake_response(body, next_url)
        return _fake_response(payload)

    rows: list[dict] = []
    with (
        patch.object(fastly, "_fetch", side_effect=fake_fetch),
        patch.object(fastly, "make_tracked_session", return_value=MagicMock()),
    ):
        for batch in get_rows(
            api_key="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
    return rows


class TestGetRowsObject:
    def test_single_object_is_wrapped_in_a_list(self) -> None:
        pages = {f"{FASTLY_BASE_URL}/current_user": {"id": "U1", "login": "a@b.com"}}
        rows = _collect("current_user", _FakeResumableManager(), pages)
        assert rows == [{"id": "U1", "login": "a@b.com"}]


class TestGetRowsServiceList:
    def test_paginates_and_saves_state_after_each_page(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], f"{FASTLY_BASE_URL}/service?page=2"),
            f"{FASTLY_BASE_URL}/service?page=2": ([{"id": "S2"}], None),
        }
        manager = _FakeResumableManager()
        rows = _collect("services", manager, pages)

        assert rows == [{"id": "S1"}, {"id": "S2"}]
        # State is saved once, after yielding page 1 (which has a next page), pointing at page 2.
        assert [s.next_url for s in manager.saved] == [f"{FASTLY_BASE_URL}/service?page=2"]

    def test_resumes_from_saved_next_url(self) -> None:
        pages = {f"{FASTLY_BASE_URL}/service?page=2": ([{"id": "S2"}], None)}
        manager = _FakeResumableManager(FastlyResumeConfig(next_url=f"{FASTLY_BASE_URL}/service?page=2"))
        rows = _collect("services", manager, pages)
        assert rows == [{"id": "S2"}]


class TestGetRowsVersionListFanOut:
    def test_fans_out_over_services(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}, {"id": "S2"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [{"service_id": "S1", "number": 1}],
            f"{FASTLY_BASE_URL}/service/S2/version": [{"service_id": "S2", "number": 2}],
        }
        manager = _FakeResumableManager()
        rows = _collect("service_versions", manager, pages)

        assert rows == [{"service_id": "S1", "number": 1}, {"service_id": "S2", "number": 2}]
        assert [s.service_id for s in manager.saved] == ["S1", "S2"]

    def test_resumes_from_saved_service_bookmark(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}, {"id": "S2"}], None),
            f"{FASTLY_BASE_URL}/service/S2/version": [{"service_id": "S2", "number": 2}],
        }
        # Bookmarked at S2 — S1 is already synced, so only S2 is (re-)processed.
        manager = _FakeResumableManager(FastlyResumeConfig(service_id="S2"))
        rows = _collect("service_versions", manager, pages)
        assert rows == [{"service_id": "S2", "number": 2}]


class TestGetRowsVersionResourceFanOut:
    def test_uses_active_version_and_injects_service_id(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [
                {"number": 1, "active": False},
                {"number": 2, "active": True},
            ],
            # Only the active version (2) is read for the resource.
            f"{FASTLY_BASE_URL}/service/S1/version/2/backend": [{"name": "origin", "version": 2}],
        }
        rows = _collect("service_backends", _FakeResumableManager(), pages)
        assert rows == [{"name": "origin", "version": 2, "service_id": "S1"}]

    def test_service_without_versions_is_skipped_but_bookmark_advances(self) -> None:
        # A versionless service yields no rows, but its bookmark must still advance so resume doesn't
        # re-evaluate it on every future run.
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}, {"id": "S2"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [],
            f"{FASTLY_BASE_URL}/service/S2/version": [{"number": 1, "active": True}],
            f"{FASTLY_BASE_URL}/service/S2/version/1/backend": [{"name": "origin", "version": 1}],
        }
        manager = _FakeResumableManager()
        rows = _collect("service_backends", manager, pages)

        assert rows == [{"name": "origin", "version": 1, "service_id": "S2"}]
        assert [s.service_id for s in manager.saved] == ["S1", "S2"]


class TestNextCursor:
    @parameterized.expand(
        [
            # Invoices carry `meta` at the top level.
            ("top_level", {"data": [], "meta": {"next_cursor": "abc"}}, "abc"),
            # The usage metrics response nests `meta` inside `data`.
            ("nested_in_data", {"data": {"meta": {"next_cursor": "def"}}}, "def"),
            ("last_page_empty_cursor", {"data": [], "meta": {"next_cursor": ""}}, None),
            ("last_page_no_cursor", {"data": [], "meta": {"total": 3}}, None),
            ("no_meta", {"data": []}, None),
        ]
    )
    def test_next_cursor(self, _name: str, payload: dict, expected: str | None) -> None:
        assert _next_cursor(payload) == expected


class TestUsageMetricsWindow:
    @parameterized.expand(
        [
            ("mid_year", datetime(2026, 9, 15, tzinfo=UTC), "2026-07", "2026-09"),
            # The three-month window has to roll back over a year boundary, not clamp to January.
            ("crosses_year", datetime(2026, 1, 3, tzinfo=UTC), "2025-11", "2026-01"),
            ("december", datetime(2026, 12, 31, tzinfo=UTC), "2026-10", "2026-12"),
        ]
    )
    def test_window_spans_three_months(self, _name: str, today: datetime, start: str, end: str) -> None:
        assert _usage_metrics_window(today) == {"start_month": start, "end_month": end}


class TestFlattenUsageMetrics:
    def test_flattens_one_row_per_usage_type_and_service(self) -> None:
        payload = {
            "data": [
                {
                    "customer_id": "C1",
                    "start_time": "2026-09-01T00:00:00Z",
                    "usage_type": "North America Requests",
                    "unit": "unit",
                    "meta": {"next_cursor": "x"},
                    "details": [
                        {"service_id": "S1", "service_name": "www", "usage_units": 10.5},
                        {"service_id": "S2", "service_name": "api", "usage_units": 2.0},
                    ],
                }
            ]
        }
        rows = _flatten_usage_metrics(payload)

        # `meta` is pagination state, not a column on the row.
        assert rows == [
            {
                "customer_id": "C1",
                "start_time": "2026-09-01T00:00:00Z",
                "usage_type": "North America Requests",
                "unit": "unit",
                "service_id": "S1",
                "service_name": "www",
                "usage_units": 10.5,
            },
            {
                "customer_id": "C1",
                "start_time": "2026-09-01T00:00:00Z",
                "usage_type": "North America Requests",
                "unit": "unit",
                "service_id": "S2",
                "service_name": "api",
                "usage_units": 2.0,
            },
        ]

    def test_accepts_a_single_data_object(self) -> None:
        # Fastly's own spec models `data` as one usage-type block rather than a list.
        payload = {"data": {"usage_type": "Bandwidth", "details": [{"service_id": "S1", "usage_units": 1.0}]}}
        assert _flatten_usage_metrics(payload) == [{"usage_type": "Bandwidth", "service_id": "S1", "usage_units": 1.0}]

    @parameterized.expand(
        [
            ("no_data", {}),
            ("null_details", {"data": {"usage_type": "Bandwidth", "details": None}}),
            ("empty_details", {"data": {"usage_type": "Bandwidth", "details": []}}),
        ]
    )
    def test_pages_without_details_yield_no_rows(self, _name: str, payload: dict) -> None:
        assert _flatten_usage_metrics(payload) == []


class TestGetRowsVersionResourceChildFanOut:
    def test_fans_out_through_the_parent_resource_and_injects_both_ids(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [{"number": 2, "active": True}],
            f"{FASTLY_BASE_URL}/service/S1/version/2/acl": [{"id": "A1"}, {"id": "A2"}],
            f"{FASTLY_BASE_URL}/service/S1/acl/A1/entries?per_page=100": [{"id": "E1", "ip": "1.2.3.4"}],
            f"{FASTLY_BASE_URL}/service/S1/acl/A2/entries?per_page=100": [{"id": "E2", "ip": "5.6.7.8"}],
        }
        rows = _collect("acl_entries", _FakeResumableManager(), pages)

        assert rows == [
            {"id": "E1", "ip": "1.2.3.4", "service_id": "S1", "acl_id": "A1"},
            {"id": "E2", "ip": "5.6.7.8", "service_id": "S1", "acl_id": "A2"},
        ]

    def test_paginates_each_parent_via_the_link_header(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [{"number": 1, "active": True}],
            f"{FASTLY_BASE_URL}/service/S1/version/1/dictionary": [{"id": "D1"}],
            f"{FASTLY_BASE_URL}/service/S1/dictionary/D1/items?per_page=100": (
                [{"item_key": "a", "item_value": "1"}],
                f"{FASTLY_BASE_URL}/service/S1/dictionary/D1/items?page=2",
            ),
            f"{FASTLY_BASE_URL}/service/S1/dictionary/D1/items?page=2": ([{"item_key": "b", "item_value": "2"}], None),
        }
        rows = _collect("dictionary_items", _FakeResumableManager(), pages)

        assert [row["item_key"] for row in rows] == ["a", "b"]
        # A dictionary item has no id, so the key needs both parents to stay unique table-wide.
        assert all(row["service_id"] == "S1" and row["dictionary_id"] == "D1" for row in rows)

    def test_bookmark_advances_once_per_service_not_per_parent(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}, {"id": "S2"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [{"number": 1, "active": True}],
            f"{FASTLY_BASE_URL}/service/S1/version/1/acl": [{"id": "A1"}, {"id": "A2"}],
            f"{FASTLY_BASE_URL}/service/S1/acl/A1/entries?per_page=100": [{"id": "E1"}],
            f"{FASTLY_BASE_URL}/service/S1/acl/A2/entries?per_page=100": [{"id": "E2"}],
            f"{FASTLY_BASE_URL}/service/S2/version": [],
        }
        manager = _FakeResumableManager()
        rows = _collect("acl_entries", manager, pages)

        assert [row["id"] for row in rows] == ["E1", "E2"]
        assert [s.service_id for s in manager.saved] == ["S1", "S2"]

    def test_parent_without_an_id_is_skipped(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [{"number": 1, "active": True}],
            f"{FASTLY_BASE_URL}/service/S1/version/1/acl": [{"name": "no-id-here"}],
        }
        assert _collect("acl_entries", _FakeResumableManager(), pages) == []


class TestGetRowsBillingList:
    def test_follows_the_cursor_and_saves_it_after_each_page(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/billing/v3/invoices?limit=200": {
                "data": [{"invoice_id": "1"}],
                "meta": {"next_cursor": "CUR2"},
            },
            f"{FASTLY_BASE_URL}/billing/v3/invoices?limit=200&cursor=CUR2": {
                "data": [{"invoice_id": "2"}],
                "meta": {"next_cursor": ""},
            },
        }
        manager = _FakeResumableManager()
        rows = _collect("invoices", manager, pages)

        assert rows == [{"invoice_id": "1"}, {"invoice_id": "2"}]
        assert [s.cursor for s in manager.saved] == ["CUR2"]

    def test_resumes_from_the_saved_cursor(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/billing/v3/invoices?limit=200&cursor=CUR2": {
                "data": [{"invoice_id": "2"}],
                "meta": {},
            },
        }
        manager = _FakeResumableManager(FastlyResumeConfig(cursor="CUR2"))
        assert _collect("invoices", manager, pages) == [{"invoice_id": "2"}]

    def test_non_dict_payload_yields_nothing(self) -> None:
        pages: dict[str, Any] = {f"{FASTLY_BASE_URL}/billing/v3/invoices?limit=200": []}
        assert _collect("invoices", _FakeResumableManager(), pages) == []


class TestGetRowsBillingUsageMetrics:
    def test_requests_a_three_month_window_and_flattens_each_page(self) -> None:
        window = _usage_metrics_window()
        first = (
            f"{FASTLY_BASE_URL}/billing/v3/service-usage-metrics"
            f"?start_month={window['start_month']}&end_month={window['end_month']}"
        )
        pages = {
            first: {
                "data": {
                    "usage_type": "Bandwidth",
                    "details": [{"service_id": "S1", "usage_units": 1.0}],
                    "meta": {"next_cursor": "CUR2"},
                }
            },
            f"{first}&cursor=CUR2": {
                "data": {
                    "usage_type": "Bandwidth",
                    "details": [{"service_id": "S2", "usage_units": 2.0}],
                    "meta": {},
                }
            },
        }
        manager = _FakeResumableManager()
        rows = _collect("billing_usage_metrics", manager, pages)

        assert [row["service_id"] for row in rows] == ["S1", "S2"]
        assert [s.cursor for s in manager.saved] == ["CUR2"]


class TestFastlySourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_primary_keys_match_settings(self, endpoint: str) -> None:
        response = fastly_source(
            api_key="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == FASTLY_ENDPOINTS[endpoint].primary_keys

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_partitions_on_a_stable_key(self, endpoint: str) -> None:
        response = fastly_source(
            api_key="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode == "datetime"
        assert response.partition_keys is not None
        # A partition key that moves rewrites every partition on each sync.
        assert not any(key.startswith(("updated", "last_", "deleted")) for key in response.partition_keys)
