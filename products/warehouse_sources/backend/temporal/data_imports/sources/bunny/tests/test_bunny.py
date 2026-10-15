from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.bunny import (
    BUNNY_BASE_URL,
    BUNNY_STREAM_BASE_URL,
    PER_PAGE,
    BunnyResumeConfig,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.settings import (
    BUNNY_ENDPOINTS,
    ENDPOINTS,
    LOG_RETENTION,
    LOG_WINDOW_MARGIN,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.source import BunnySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bunny import BunnySourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(BunnySource(), BunnySourceConfig(access_key="bunny-key"))


def _response(
    items: list[dict[str, Any]] | None,
    *,
    has_more: bool = False,
    drop_items: bool = False,
    status_code: int = 200,
) -> ScriptedResponse:
    body: dict[str, Any] = {"CurrentPage": 1, "TotalItems": len(items or []), "HasMoreItems": has_more}
    if not drop_items:
        body["Items"] = items or []
    return ScriptedResponse(status=status_code, json=body)


def _raw_response(body: Any, *, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


def _stream_response(items: list[dict[str, Any]]) -> ScriptedResponse:
    return _raw_response({"items": items, "totalItems": len(items), "currentPage": 1, "itemsPerPage": PER_PAGE})


def _log_response(entries: list[dict[str, Any]] | None, *, has_more: bool = False) -> ScriptedResponse:
    return _raw_response(
        {
            "data": entries,
            "pagination": {"offset": 0, "limit": PER_PAGE, "returned": len(entries or []), "hasMore": has_more},
            "query": {"pullZoneId": 1, "from": "2024-05-01T00:00:00Z", "to": "2024-05-02T00:00:00Z", "order": "asc"},
        }
    )


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        # Page 1 must never be fetched on resume.
        result = _driver().run(
            "pull_zones",
            [_response([{"Id": 2}], has_more=True), _response([{"Id": 3}])],
            resume_state=BunnyResumeConfig(next_page=2),
        )

        assert result.raised is None
        assert result.rows == [{"Id": 2}, {"Id": 3}]
        assert result.params("page") == ["2", "3"]

    def test_missing_items_key_raises_loudly(self) -> None:
        # A 200 body without "Items" means the response shape changed — fail loud, not silently 0 rows.
        result = _driver().run("pull_zones", [_response(None, drop_items=True)])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)

    def test_access_key_travels_via_redacting_auth(self) -> None:
        result = _driver().run("pull_zones", [_response([{"Id": 1}])])

        assert result.raised is None
        assert result.requests[0].headers["accesskey"] == "bunny-key"
        assert result.requests[0].headers["accept"] == "application/json"
        assert any(options.get("redact_values") == ("bunny-key",) for options in result.session_options)


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_are_retried_then_succeed(self, _name: str, status: int) -> None:
        result = _driver().run("pull_zones", [_response([], status_code=status), _response([{"Id": 1}])])

        assert result.raised is None
        assert result.rows == [{"Id": 1}]
        assert len(result.requests) == 2

    def test_persistent_server_error_exhausts_retries(self) -> None:
        result = _driver().run("pull_zones", always(_response([], status_code=500)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        result = _driver().run("pull_zones", [_response([], status_code=status)])

        assert isinstance(result.raised, requests.HTTPError)
        # Credential problems are permanent — no retries.
        assert len(result.requests) == 1


class TestCheckAccess:
    def test_connection_error_maps_to_none(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            assert check_access("bunny-key") == (False, None)
        assert network.requests_log
        assert {request.path for request in network.requests_log} == {"/pullzone"}


class TestBunnySourceResponse:
    @parameterized.expand(
        [
            ("pull_zones", ["Id"], None),
            ("storage_zones", ["Id"], None),
            ("dns_zones", ["Id"], "DateCreated"),
            ("dns_records", ["DnsZoneId", "Id"], None),
            ("dns_zone_statistics", ["DnsZoneId", "Timestamp"], "Timestamp"),
            ("pull_zone_logs", ["pullZoneId", "requestId"], "timestamp"),
            ("video_libraries", ["Id"], "DateCreated"),
            ("statistics", ["Timestamp"], "Timestamp"),
            ("storage_zone_statistics", ["StorageZoneId", "Timestamp"], "Timestamp"),
            ("storage_zone_egress", ["StorageZoneId", "Timestamp"], "Timestamp"),
            ("videos", ["videoLibraryId", "guid"], "dateUploaded"),
            ("video_collections", ["videoLibraryId", "guid"], None),
            ("video_library_statistics", ["videoLibraryId", "timestamp"], "timestamp"),
        ]
    )
    def test_partitioning_matches_endpoint_config(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        empty = {"Items": [], "items": [], "data": [], "pagination": {"hasMore": False}}
        result = _driver().run(endpoint, always(ScriptedResponse(json=empty)))
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == primary_keys
        if partition_key is None:
            assert result.response.partition_mode is None
            assert result.response.partition_keys is None
        else:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_keys == [partition_key]

    def test_top_level_endpoints_use_the_globally_unique_id(self) -> None:
        # bunny.net IDs are globally unique, so a single `Id` key is sufficient table-wide.
        top_level = [c for c in BUNNY_ENDPOINTS.values() if c.parent is None and c.charts is None]
        assert all(config.primary_keys == ["Id"] for config in top_level)
        assert set(BUNNY_ENDPOINTS) == set(ENDPOINTS)

    def test_fanout_children_carry_their_parent_id_in_the_key(self) -> None:
        # A child aggregates rows from every parent into one table, so a key unique only within a
        # parent seeds duplicate rows that every later merge multi-matches.
        children = [c for c in BUNNY_ENDPOINTS.values() if c.parent is not None]
        assert children
        assert all(config.parent is not None and config.parent.id_column in config.primary_keys for config in children)

    def test_fanout_tables_defer_the_watermark_to_the_end_of_the_run(self) -> None:
        # Their rows arrive grouped by parent, so the table is not in timestamp order and a run cut
        # short mid-walk must not leave the watermark past parents it never reached.
        for config in BUNNY_ENDPOINTS.values():
            if config.parent is not None and config.timestamp_column is not None:
                assert config.sort_mode == "desc"


class TestAccountStatistics:
    def test_full_refresh_asks_for_the_charts_without_a_date_bound(self) -> None:
        result = _driver().run("statistics", [_raw_response({"BandwidthUsedChart": {"2024-05-01T00:00:00": 1}})])

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.requests[0].url.startswith(f"{BUNNY_BASE_URL}/statistics")
        # Each chart defaults to off, so a missing load flag silently returns an empty column.
        assert result.requests[0].param("loadBandwidthUsed") == "true"
        assert result.requests[0].param("loadRequestsServed") == "true"
        assert result.requests[0].param("dateFrom") is None

    @parameterized.expand(
        [
            ("datetime", datetime(2024, 5, 2, 3, 4, 5, tzinfo=UTC)),
            # The pipeline persists the watermark as a string for some sources.
            ("string", "2024-05-02T03:04:05+00:00"),
        ]
    )
    def test_incremental_asks_from_the_watermark(self, _name: str, last_value: Any) -> None:
        result = _driver().run(
            "statistics",
            [_raw_response({"BandwidthUsedChart": {}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.requests[0].param("dateFrom") == "2024-05-02T03:04:05Z"


class TestStreamFanout:
    @parameterized.expand(
        [
            ("videos", "/library/7/videos", {"guid": "g1", "videoLibraryId": 7}),
            ("video_collections", "/library/7/collections", {"guid": "c1", "videoLibraryId": 7, "name": "Launch"}),
        ]
    )
    def test_lists_use_the_library_key_against_the_stream_host(
        self, endpoint: str, expected_path: str, row: dict[str, Any]
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _response([{"Id": 7, "ReadOnlyApiKey": "lib-ro", "ApiKey": "lib-rw"}]),
                _stream_response([row]),
                _stream_response([]),
            ],
        )

        assert result.raised is None
        assert result.rows == [row]
        # The account key lists the libraries; the Stream host only accepts the library's own key.
        assert result.requests[0].headers["accesskey"] == "bunny-key"
        assert result.requests[1].url.startswith(f"{BUNNY_STREAM_BASE_URL}{expected_path}")
        assert result.requests[1].headers["accesskey"] == "lib-ro"
        assert result.requests[1].query == {"page": ("1",), "itemsPerPage": (str(PER_PAGE),), "orderBy": ("date",)}
        # The Stream envelope carries no "more items" flag, so the walk ends on an empty page.
        assert result.params("page")[1:] == ["1", "2"]

    def test_library_without_a_key_is_skipped(self) -> None:
        # A library we cannot authenticate against must not fail the whole table.
        result = _driver().run("videos", [_response([{"Id": 7}])])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1


class TestPullZoneLogs:
    def test_the_decrypted_authorization_header_never_reaches_a_row(self) -> None:
        result = _driver().run(
            "pull_zone_logs",
            [
                _response([{"Id": 3}]),
                _log_response([{"requestId": "a", "authorizationHeader": "Bearer not-ours-to-keep", "path": "/x"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"pullZoneId": 3, "requestId": "a", "path": "/x"}]

    def test_a_zone_with_logging_turned_off_is_skipped(self) -> None:
        # 404 means logging is off for that zone, so the remaining zones must still sync.
        result = _driver().run(
            "pull_zone_logs",
            [
                _response([{"Id": 3}, {"Id": 4}]),
                _raw_response({"error": "Logging is not enabled for this pull zone"}, status_code=404),
                _log_response([{"requestId": "b"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"pullZoneId": 4, "requestId": "b"}]

    def test_an_auth_failure_still_fails_the_table(self) -> None:
        result = _driver().run(
            "pull_zone_logs",
            [_response([{"Id": 3}]), _raw_response({"error": "x"}, status_code=403)],
        )

        assert isinstance(result.raised, requests.HTTPError)

    @parameterized.expand(
        [
            # No watermark yet: seed the whole window bunny.net still retains.
            ("first_run", None, LOG_RETENTION - LOG_WINDOW_MARGIN),
            # A watermark inside the window is asked from as-is.
            ("recent_watermark", timedelta(hours=6), timedelta(hours=6)),
            # An older one is clamped, because the API rejects a window starting before retention.
            ("stale_watermark", timedelta(days=30), LOG_RETENTION - LOG_WINDOW_MARGIN),
        ]
    )
    def test_asks_from_the_watermark_clamped_to_retention(
        self, _name: str, watermark_age: timedelta | None, expected_age: timedelta
    ) -> None:
        now = datetime.now(UTC)
        result = _driver().run(
            "pull_zone_logs",
            [_response([{"Id": 3}]), _log_response([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None if watermark_age is None else now - watermark_age,
        )

        assert result.raised is None
        asked_value = result.requests[1].param("from")
        assert asked_value is not None
        asked = datetime.strptime(asked_value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert abs((now - expected_age) - asked) < timedelta(minutes=1)
