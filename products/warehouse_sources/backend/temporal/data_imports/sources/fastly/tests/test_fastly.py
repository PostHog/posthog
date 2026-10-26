from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly import fastly
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.fastly import (
    FASTLY_BASE_URL,
    ORIGIN_INSPECTOR_PAGE_LIMIT,
    FastlyPaginationError,
    FastlyResumeConfig,
    FastlyRetryableError,
    _active_version_number,
    _as_epoch_seconds,
    _bucket_timeline,
    _build_url,
    _ensure_service_id,
    _flatten_json_api,
    _flatten_origin_inspector,
    _flatten_usage_metrics,
    _next_cursor,
    _usage_metrics_window,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.settings import ENDPOINTS, FASTLY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.source import FastlySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fastly import FastlySourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(FastlySource(), FastlySourceConfig(api_key="token"))


def _drive(
    endpoint: str,
    pages: dict[str, Any],
    *,
    resume_state: FastlyResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    def answer(request: RecordedRequest) -> ScriptedResponse:
        url = unquote(request.url)
        if url not in pages:
            raise UnexpectedRequest(f"No Fastly response for {url}")
        payload = pages[url]
        if isinstance(payload, ScriptedResponse):
            return payload
        if isinstance(payload, tuple):
            body, next_url = payload
            headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
            return ScriptedResponse(json=body, headers=headers)
        return ScriptedResponse(json=payload)

    return _driver().run(endpoint, answer, resume_state=resume_state, **inputs)


class TestBuildUrl:
    def test_no_params_returns_base(self) -> None:
        assert _build_url(f"{FASTLY_BASE_URL}/service", {}) == f"{FASTLY_BASE_URL}/service"


class TestEnsureServiceId:
    def test_injects_missing_service_id(self) -> None:
        assert _ensure_service_id({"name": "www"}, "SVC")["service_id"] == "SVC"


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
        response = MagicMock()
        response.json.return_value = versions
        with patch.object(fastly, "_fetch", return_value=response):
            assert _active_version_number(session, "SVC", {}, MagicMock()) == expected


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True)])
    def test_validate_credentials_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("token") is expected
        assert [request.path for request in network.requests_log] == ["/current_user"]
        assert network.requests_log[0].headers["fastly-key"] == "token"


class TestTokenRedaction:
    # The token rides in the custom `Fastly-Key` header, which the transport's name-based scrubber
    # doesn't know about — both entry points must pass it as a redact value or it leaks into samples.
    def test_validate_credentials_redacts_token(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("secret-token")
        assert network.session_options[0]["redact_values"] == ("secret-token",)

    def test_get_rows_redacts_token(self) -> None:
        result = SourceDriver(FastlySource(), FastlySourceConfig(api_key="secret-token")).run(
            "current_user", [ScriptedResponse(json={"id": "U1"})]
        )
        assert result.rows == [{"id": "U1"}]
        assert result.session_options[0]["redact_values"] == ("secret-token",)


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


class TestGetRowsObject:
    def test_single_object_is_wrapped_in_a_list(self) -> None:
        pages = {f"{FASTLY_BASE_URL}/current_user": {"id": "U1", "login": "a@b.com"}}
        result = _drive("current_user", pages)
        assert result.raised is None
        assert result.rows == [{"id": "U1", "login": "a@b.com"}]
        assert result.items == [[{"id": "U1", "login": "a@b.com"}]]


class TestGetRowsServiceList:
    def test_paginates_and_saves_state_after_each_page(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], f"{FASTLY_BASE_URL}/service?page=2"),
            f"{FASTLY_BASE_URL}/service?page=2": ([{"id": "S2"}], None),
        }
        result = _drive("services", pages)

        assert result.raised is None
        assert result.rows == [{"id": "S1"}, {"id": "S2"}]
        assert result.params("per_page") == ["100", None]
        assert result.params("page") == [None, "2"]
        # State is saved once, after yielding page 1 (which has a next page), pointing at page 2.
        assert result.saved_states == [FastlyResumeConfig(next_url=f"{FASTLY_BASE_URL}/service?page=2")]

    def test_resumes_from_saved_next_url(self) -> None:
        pages = {f"{FASTLY_BASE_URL}/service?page=2": ([{"id": "S2"}], None)}
        result = _drive(
            "services", pages, resume_state=FastlyResumeConfig(next_url=f"{FASTLY_BASE_URL}/service?page=2")
        )
        assert result.raised is None
        assert result.rows == [{"id": "S2"}]
        assert result.params("page") == ["2"]


class TestGetRowsVersionListFanOut:
    def test_resumes_from_saved_service_bookmark(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}, {"id": "S2"}], None),
            f"{FASTLY_BASE_URL}/service/S2/version": [{"service_id": "S2", "number": 2}],
        }
        # Bookmarked at S2 — S1 is already synced, so only S2 is (re-)processed.
        result = _drive("service_versions", pages, resume_state=FastlyResumeConfig(service_id="S2"))
        assert result.raised is None
        assert result.rows == [{"service_id": "S2", "number": 2}]
        assert result.paths == ["/service", "/service/S2/version"]


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
        result = _drive("service_backends", pages)
        assert result.raised is None
        assert result.rows == [{"name": "origin", "version": 2, "service_id": "S1"}]
        assert result.paths[-1] == "/service/S1/version/2/backend"

    def test_service_without_versions_is_skipped_but_bookmark_advances(self) -> None:
        # A versionless service yields no rows, but its bookmark must still advance so resume doesn't
        # re-evaluate it on every future run.
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}, {"id": "S2"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [],
            f"{FASTLY_BASE_URL}/service/S2/version": [{"number": 1, "active": True}],
            f"{FASTLY_BASE_URL}/service/S2/version/1/backend": [{"name": "origin", "version": 1}],
        }
        result = _drive("service_backends", pages)

        assert result.raised is None
        assert result.rows == [{"name": "origin", "version": 1, "service_id": "S2"}]
        assert [state.service_id for state in result.saved_states] == ["S1", "S2"]


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
        result = _drive("acl_entries", pages)

        assert result.raised is None
        assert result.rows == [
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
        result = _drive("dictionary_items", pages)

        assert result.raised is None
        assert [row["item_key"] for row in result.rows] == ["a", "b"]
        assert result.params("page")[-2:] == [None, "2"]
        # A dictionary item has no id, so the key needs both parents to stay unique table-wide.
        assert all(row["service_id"] == "S1" and row["dictionary_id"] == "D1" for row in result.rows)

    def test_write_only_dictionary_is_not_requested(self) -> None:
        # Fastly refuses to list the items of a write-only dictionary, which would abort the sync.
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [{"number": 1, "active": True}],
            f"{FASTLY_BASE_URL}/service/S1/version/1/dictionary": [
                {"id": "D1", "write_only": True},
                {"id": "D2", "write_only": False},
            ],
            f"{FASTLY_BASE_URL}/service/S1/dictionary/D2/items?per_page=100": [{"item_key": "a"}],
        }
        result = _drive("dictionary_items", pages)
        assert result.raised is None
        assert [row["dictionary_id"] for row in result.rows] == ["D2"]
        assert "/service/S1/dictionary/D1/items" not in result.paths

    def test_repeated_next_link_stops_instead_of_looping(self) -> None:
        self_referencing = f"{FASTLY_BASE_URL}/service/S1/acl/A1/entries?per_page=100"
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [{"number": 1, "active": True}],
            f"{FASTLY_BASE_URL}/service/S1/version/1/acl": [{"id": "A1"}],
            self_referencing: ([{"id": "E1"}], self_referencing),
        }
        result = _drive("acl_entries", pages)
        assert isinstance(result.raised, FastlyPaginationError)
        assert result.paths.count("/service/S1/acl/A1/entries") == 1

    def test_parent_without_an_id_is_skipped(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], None),
            f"{FASTLY_BASE_URL}/service/S1/version": [{"number": 1, "active": True}],
            f"{FASTLY_BASE_URL}/service/S1/version/1/acl": [{"name": "no-id-here"}],
        }
        result = _drive("acl_entries", pages)
        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 3


class TestGetRowsBillingList:
    def test_resumes_from_the_saved_cursor(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/billing/v3/invoices?limit=200&cursor=CUR2": {
                "data": [{"invoice_id": "2"}],
                "meta": {},
            },
        }
        result = _drive(
            "invoices",
            pages,
            resume_state=FastlyResumeConfig(cursor="CUR2", cursor_request="/billing/v3/invoices?limit=200"),
        )
        assert result.raised is None
        assert result.rows == [{"invoice_id": "2"}]
        assert result.params("cursor") == ["CUR2"]

    def test_repeated_cursor_stops_instead_of_looping(self) -> None:
        # A cursor pointing back at the page just read would re-fetch and re-yield it forever.
        pages = {
            f"{FASTLY_BASE_URL}/billing/v3/invoices?limit=200": {
                "data": [{"invoice_id": "1"}],
                "meta": {"next_cursor": "CUR2"},
            },
            f"{FASTLY_BASE_URL}/billing/v3/invoices?limit=200&cursor=CUR2": {
                "data": [{"invoice_id": "2"}],
                "meta": {"next_cursor": "CUR2"},
            },
        }
        result = _drive("invoices", pages)
        assert isinstance(result.raised, FastlyPaginationError)
        assert result.rows == [{"invoice_id": "1"}, {"invoice_id": "2"}]
        assert result.params("cursor") == [None, "CUR2"]

    def test_non_dict_payload_yields_nothing(self) -> None:
        pages: dict[str, Any] = {f"{FASTLY_BASE_URL}/billing/v3/invoices?limit=200": []}
        result = _drive("invoices", pages)
        assert result.raised is None
        assert result.rows == []


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
        result = _drive("billing_usage_metrics", pages)

        assert result.raised is None
        assert [row["service_id"] for row in result.rows] == ["S1", "S2"]
        assert result.params("cursor") == [None, "CUR2"]
        assert [state.cursor for state in result.saved_states] == ["CUR2"]


class TestFastlySourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_primary_keys_match_settings(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == FASTLY_ENDPOINTS[endpoint].primary_keys

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_partitions_on_a_stable_key(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])
        response = result.response
        assert response is not None
        if FASTLY_ENDPOINTS[endpoint].partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
            return

        assert response.partition_mode == "datetime"
        assert response.partition_keys is not None
        # A partition key that moves rewrites every partition on each sync.
        assert not any(key.startswith(("updated", "last_", "deleted")) for key in response.partition_keys)

    @parameterized.expand(
        [
            ("epoch_int", 1_700_000_000, 1_700_000_000),
            ("epoch_float", 1_700_000_000.9, 1_700_000_000),
            ("datetime", datetime(2026, 9, 1, tzinfo=UTC), 1_788_220_800),
            ("unusable", "2026-09-01", None),
        ]
    )
    def test_watermark_is_normalised_to_unix_seconds(self, _name: str, value: Any, expected: int | None) -> None:
        assert _as_epoch_seconds(value) == expected

    def test_full_refresh_sends_no_watermark(self) -> None:
        # The watermark is only read when the run is actually incremental; a full refresh has to ask
        # for the API's own default window instead of resending the last cursor.
        result = _driver().run(
            "historical_stats",
            [ScriptedResponse(json={"data": {}})],
            should_use_incremental_field=False,
            db_incremental_field_last_value=1_700_000_000,
        )
        assert result.raised is None
        assert result.urls == [f"{FASTLY_BASE_URL}/stats?by=day"]


class TestGetRowsPlainList:
    @parameterized.expand(
        [
            # /datacenters answers with a bare array rather than the usual `{"data": [...]}` wrapper.
            ("array", [{"code": "IAD"}, {"code": "SYD"}], [{"code": "IAD"}, {"code": "SYD"}]),
            ("error_object", {"msg": "nope"}, []),
        ]
    )
    def test_unpaginated_array_is_yielded_as_one_batch(self, _name: str, payload: Any, expected: list) -> None:
        pages = {f"{FASTLY_BASE_URL}/datacenters": payload}
        result = _drive("pops", pages)
        assert result.raised is None
        assert result.rows == expected
        if expected:
            assert result.items == [expected]


class TestFlattenJsonApi:
    @parameterized.expand(
        [
            (
                "full_resource",
                {
                    "id": "SA1",
                    "type": "service_authorization",
                    "attributes": {"permission": "full", "created_at": "2026-09-01T00:00:00Z"},
                    "relationships": {
                        "service": {"data": {"id": "S1", "type": "service"}},
                        "user": {"data": {"id": "U1", "type": "user"}},
                    },
                },
                {
                    "id": "SA1",
                    "type": "service_authorization",
                    "permission": "full",
                    "created_at": "2026-09-01T00:00:00Z",
                    "service_id": "S1",
                    "user_id": "U1",
                },
            ),
            ("no_attributes_or_relationships", {"id": "SA1"}, {"id": "SA1"}),
            # A relationship can come back empty once the related object is deleted.
            ("empty_relationship", {"id": "SA1", "relationships": {"user": {"data": None}}}, {"id": "SA1"}),
        ]
    )
    def test_lifts_attributes_and_relationship_ids_into_the_row(self, _name: str, item: dict, expected: dict) -> None:
        assert _flatten_json_api(item) == expected


class TestGetRowsJsonApiList:
    def test_flattens_rows_and_follows_the_body_link(self) -> None:
        first = f"{FASTLY_BASE_URL}/service-authorizations?page[size]=100"
        second = f"{FASTLY_BASE_URL}/service-authorizations?page[number]=2&page[size]=100"
        pages = {
            # Fastly returns the next page as a path, which has to resolve against the API host.
            first: {
                "data": [{"id": "SA1", "relationships": {"service": {"data": {"id": "S1"}}}}],
                "links": {"next": "/service-authorizations?page[number]=2&page[size]=100"},
            },
            second: {"data": [{"id": "SA2", "attributes": {"permission": "read_only"}}], "links": {}},
        }
        result = _drive("service_authorizations", pages)

        assert result.raised is None
        assert result.rows == [{"id": "SA1", "service_id": "S1"}, {"id": "SA2", "permission": "read_only"}]
        assert result.params("page[size]") == ["100", "100"]
        assert result.params("page[number]") == [None, "2"]
        assert [state.next_url for state in result.saved_states] == [second]

    def test_resumes_from_the_saved_page_url(self) -> None:
        second = f"{FASTLY_BASE_URL}/service-authorizations?page[number]=2&page[size]=100"
        pages = {second: {"data": [{"id": "SA2"}], "links": {}}}
        result = _drive("service_authorizations", pages, resume_state=FastlyResumeConfig(next_url=second))
        assert result.raised is None
        assert result.rows == [{"id": "SA2"}]
        assert result.params("page[number]") == ["2"]

    def test_repeated_next_link_stops_instead_of_looping(self) -> None:
        first = f"{FASTLY_BASE_URL}/service-authorizations?page[size]=100"
        pages = {first: {"data": [{"id": "SA1"}], "links": {"next": "/service-authorizations?page[size]=100"}}}
        result = _drive("service_authorizations", pages)
        assert isinstance(result.raised, FastlyPaginationError)
        assert len(result.requests) == 1

    @parameterized.expand([("absolute", "https://evil.example.com/x"), ("scheme_relative", "//evil.example.com/x")])
    def test_off_host_next_link_is_refused(self, _name: str, next_link: str) -> None:
        # Every request carries the token in `Fastly-Key`, so following a link to another host would
        # hand that host the customer's Fastly credential.
        first = f"{FASTLY_BASE_URL}/service-authorizations?page[size]=100"
        pages = {first: {"data": [{"id": "SA1"}], "links": {"next": next_link}}}
        result = _drive("service_authorizations", pages)
        assert isinstance(result.raised, FastlyPaginationError)
        assert [request.origin for request in result.requests] == [FASTLY_BASE_URL]

    def test_off_host_resume_url_is_refused(self) -> None:
        result = _drive(
            "service_authorizations", {}, resume_state=FastlyResumeConfig(next_url="https://evil.example.com/x")
        )
        assert isinstance(result.raised, FastlyPaginationError)
        assert result.requests == []


class TestGetRowsStatsList:
    def test_incremental_run_sends_the_watermark_as_from(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/stats?by=day&from=1700000000": {"data": {"S1": [{"start_time": 1700086400}]}},
        }
        result = _drive(
            "historical_stats",
            pages,
            incremental_field="start_time",
            db_incremental_field_last_value=1_700_000_000,
        )
        assert result.raised is None
        assert result.rows == [{"start_time": 1700086400, "service_id": "S1"}]
        assert result.params("from") == ["1700000000"]

    @parameterized.expand([("not_a_dict", {"data": []}), ("no_data", {"status": "error"})])
    def test_unusable_payloads_yield_nothing(self, _name: str, payload: dict) -> None:
        result = _drive("historical_stats", {f"{FASTLY_BASE_URL}/stats?by=day": payload})
        assert result.raised is None
        assert result.rows == []


class TestGetRowsAiUsageMetrics:
    URL = f"{FASTLY_BASE_URL}/ai-runtime-control/v1/usage-metrics?granularity=daily&sort=date"

    @parameterized.expand(
        [
            ("full_refresh", False, None),
            ("incremental", True, "2023-11-14T22:13:20Z"),
        ]
    )
    def test_watermark_is_sent_as_an_rfc3339_from(self, _name: str, incremental: bool, expected: str | None) -> None:
        url = f"{self.URL}&from={expected}" if expected else self.URL
        result = _drive(
            "ai_usage_metrics",
            {url: {"data": [], "meta": {"sort": "date", "total": 0}}},
            should_use_incremental_field=incremental,
            incremental_field="start_time",
            db_incremental_field_last_value=1_700_000_000,
        )
        assert result.raised is None
        assert result.params("from") == [expected]

    def test_each_row_gets_its_day_as_start_time(self) -> None:
        # The docs give `YYYY-MM-DD` while live responses carry a full timestamp; a row without a
        # readable date has no partition or key and is dropped.
        payload = {
            "data": [
                {"date": "2026-09-01T00:00:00Z", "usage_type": "requests", "quantity": 3},
                {"date": "2026-09-02", "usage_type": "input_tokens", "quantity": 40},
                {"date": "2026-09-03 00:00:00", "usage_type": "output_tokens", "quantity": 50},
                {"date": None, "usage_type": "sessions", "quantity": 1},
            ],
            "meta": {"sort": "date", "total": 4},
        }
        result = _drive("ai_usage_metrics", {self.URL: payload})
        assert result.raised is None
        assert [(row["usage_type"], row["start_time"]) for row in result.rows] == [
            ("requests", 1_788_220_800),
            ("input_tokens", 1_788_307_200),
            ("output_tokens", 1_788_393_600),
        ]


class TestBucketTimeline:
    @parameterized.expand(
        [
            ("day", {"start": "2026-09-01T00:00:00Z", "downsample": "day"}, (1_788_220_800, 86400)),
            ("hour", {"start": "2026-09-01T00:00:00Z", "downsample": "hour"}, (1_788_220_800, 3600)),
            # A start without a zone is UTC, as every absolute time in the Fastly metrics APIs is.
            ("naive_start_is_utc", {"start": "2026-09-01T00:00:00", "downsample": "day"}, (1_788_220_800, 86400)),
            ("unknown_downsample", {"start": "2026-09-01T00:00:00Z", "downsample": "fortnight"}, None),
            ("missing_start", {"downsample": "day"}, None),
            ("unparseable_start", {"start": "whenever", "downsample": "day"}, None),
        ]
    )
    def test_bucket_timeline(self, _name: str, meta: dict, expected: tuple[int, int] | None) -> None:
        timeline = _bucket_timeline(meta)
        if expected is None:
            assert timeline is None
            return
        assert timeline is not None
        assert (timeline.first_start_time, timeline.bucket_seconds) == expected


class TestFlattenOriginInspector:
    @parameterized.expand(
        [
            ("no_meta", {"data": [{"dimensions": {}, "values": [{"responses": 1}]}]}),
            ("no_data", {"meta": {"start": "2026-09-01T00:00:00Z", "downsample": "day"}}),
            (
                "values_not_a_list",
                {
                    "meta": {"start": "2026-09-01T00:00:00Z", "downsample": "day"},
                    "data": [{"dimensions": {}, "values": None}],
                },
            ),
        ]
    )
    def test_unusable_payloads_yield_no_rows(self, _name: str, payload: dict) -> None:
        assert _flatten_origin_inspector(payload, "S1") == []


class TestGetRowsOriginInspector:
    def _url(self, service_id: str, cursor: str | None = None, start: int | None = None) -> str:
        params: dict[str, Any] = {
            "downsample": "day",
            "group_by": "host",
            "limit": ORIGIN_INSPECTOR_PAGE_LIMIT,
        }
        if start is not None:
            params["start"] = start
        if cursor is not None:
            params["cursor"] = cursor
        return _build_url(f"{FASTLY_BASE_URL}/metrics/origins/services/{service_id}", params)

    @parameterized.expand([("forbidden", 403), ("not_found", 404)])
    def test_service_without_the_origin_inspector_upgrade_is_skipped(self, _name: str, status_code: int) -> None:
        # Only some services carry the paid upgrade; the rest must not fail the whole table.
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}, {"id": "S2"}], None),
            self._url("S1"): ScriptedResponse(status=status_code),
            self._url("S2"): {
                "meta": {"start": "2026-09-01T00:00:00Z", "downsample": "day"},
                "data": [{"dimensions": {"host": "c"}, "values": [{"responses": 3}]}],
            },
        }
        result = _drive("origin_inspector", pages)
        assert result.raised is None
        assert [row["service_id"] for row in result.rows] == ["S2"]
        assert result.paths == ["/service", "/metrics/origins/services/S1", "/metrics/origins/services/S2"]

    def test_other_errors_still_fail_the_sync(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], None),
            self._url("S1"): ScriptedResponse(status=401),
        }
        result = _drive("origin_inspector", pages)
        assert isinstance(result.raised, requests.HTTPError)

    def test_incremental_run_sends_the_watermark_as_start(self) -> None:
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], None),
            self._url("S1", start=1_700_000_000): {
                "meta": {"start": "2026-09-01T00:00:00Z", "downsample": "day"},
                "data": [{"dimensions": {"host": "a"}, "values": [{"responses": 1}]}],
            },
        }
        result = _drive(
            "origin_inspector",
            pages,
            incremental_field="start_time",
            db_incremental_field_last_value=1_700_000_000,
        )
        assert result.raised is None
        assert [row["host"] for row in result.rows] == ["a"]
        assert result.params("start")[-1] == "1700000000"

    def test_repeated_cursor_stops_instead_of_looping(self) -> None:
        meta = {"start": "2026-09-01T00:00:00Z", "downsample": "day", "next_cursor": "CUR2"}
        pages = {
            f"{FASTLY_BASE_URL}/service?per_page=100": ([{"id": "S1"}], None),
            self._url("S1"): {"meta": meta, "data": []},
            self._url("S1", cursor="CUR2"): {"meta": meta, "data": []},
        }
        result = _drive("origin_inspector", pages)
        assert isinstance(result.raised, FastlyPaginationError)
        assert result.params("cursor") == [None, None, "CUR2"]
