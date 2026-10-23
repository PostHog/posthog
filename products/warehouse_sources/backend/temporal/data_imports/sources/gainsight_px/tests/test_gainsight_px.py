from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.gainsight_px import (
    GainsightPxResumeConfig,
    _base_url,
    _to_epoch_millis,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import (
    GAINSIGHT_PX_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.source import GainsightPxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gainsightpx import (
    GainsightPxSourceConfig,
)


def _response(data_key: str, records: list[dict[str, Any]], **extra: Any) -> ScriptedResponse:
    return ScriptedResponse(json={data_key: records, **extra})


def _driver() -> SourceDriver:
    return SourceDriver(GainsightPxSource(), GainsightPxSourceConfig(api_key="secret-key", region="us"))


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", "https://api.aptrinsic.com/v1"),
            ("eu", "https://api-eu.aptrinsic.com/v1"),
            ("us2", "https://api-us2.aptrinsic.com/v1"),
            ("unknown", "https://api.aptrinsic.com/v1"),
        ]
    )
    def test_base_url(self, region: str, expected: str) -> None:
        assert _base_url(region) == expected


class TestScrollPagination:
    def test_follows_scroll_id_and_stops_on_short_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # users caps at a large pageSize; shrink it so a 2-then-1 record run terminates.
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["users"], "page_size", 2)
        result = _driver().run(
            "users",
            [
                _response("users", [{"id": "1"}, {"id": "2"}], scrollId="s1"),
                _response("users", [{"id": "3"}], scrollId="s2"),  # short page → stop
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        # First request carries only pageSize; the second carries the scroll cursor.
        assert result.queries[0] == {"pageSize": ("2",)}
        assert result.requests[1].param("scrollId") == "s1"
        # State saved after the first (full) page only, carrying the next scroll cursor.
        assert result.saved_states == [GainsightPxResumeConfig(scroll_id="s1")]

    def test_resumes_from_saved_scroll_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["users"], "page_size", 2)
        result = _driver().run(
            "users",
            [_response("users", [{"id": "9"}], scrollId=None)],
            resume_state=GainsightPxResumeConfig(scroll_id="saved-cursor"),
        )

        assert result.raised is None
        assert result.requests[0].param("scrollId") == "saved-cursor"


class TestPageNumberPagination:
    def test_stops_on_is_last_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # page_size 1 keeps each page "full", so isLastPage (not the short-page guard) is what stops us.
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["features"], "page_size", 1)
        result = _driver().run(
            "features",
            [
                _response("features", [{"id": "f1"}], isLastPage=False),
                _response("features", [{"id": "f2"}], isLastPage=True),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["f1", "f2"]
        assert result.params("pageNumber") == ["0", "1"]
        assert result.saved_states == [GainsightPxResumeConfig(page_number=1)]

    def test_resumes_from_saved_page_number(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["features"], "page_size", 100)
        result = _driver().run(
            "features",
            [_response("features", [{"id": "f"}], isLastPage=True)],
            resume_state=GainsightPxResumeConfig(page_number=4),
        )

        assert result.raised is None
        assert result.params("pageNumber") == ["4"]


# Maxima published in the vendor's OpenAPI spec (https://px-apidocs.gainsight.com/source.json). A
# pageSize above an endpoint's maximum is rejected with a 400 and fails the whole table.
VENDOR_PAGE_SIZE_MAXIMA: dict[str, int] = {
    "accounts": 1000,
    "articles": 500,
    "engagements": 500,
    "features": 200,
    "kc_bots": 500,
    "segments": 200,
    "users": 1000,
    "page_view_events": 1000,
    "session_events": 1000,
    "engagement_view_events": 1000,
    "feature_match_events": 1000,
    "segment_match_events": 1000,
    "custom_events": 1000,
    "identify_events": 1000,
    "survey_responses": 1000,
}


class TestPageSizeCaps:
    @parameterized.expand(sorted(VENDOR_PAGE_SIZE_MAXIMA.items()))
    def test_requested_page_size_is_within_vendor_cap(self, endpoint: str, maximum: int) -> None:
        data_key = GAINSIGHT_PX_ENDPOINTS[endpoint].data_key
        result = _driver().run(endpoint, always(_response(data_key, [{"id": "1"}], isLastPage=True, scrollId=None)))

        assert result.raised is None
        assert result.rows
        page_size = result.requests[0].param("pageSize")
        assert page_size is not None
        assert int(page_size) <= maximum


# Response list keys published in the vendor's OpenAPI spec. They differ per event stream, and a
# wrong key silently yields an empty table.
VENDOR_EVENT_DATA_KEYS: dict[str, str] = {
    "page_view_events": "results",
    "session_events": "sessionInitializedEvents",
    "engagement_view_events": "results",
    "feature_match_events": "featureMatchEvents",
    "segment_match_events": "featureMatchEvents",
    "custom_events": "customEvents",
    "identify_events": "identifyEvents",
    "survey_responses": "results",
}


NOW = datetime(2021, 1, 2, tzinfo=UTC)
NOW_MS = 1609545600000
DAY_MS = 24 * 60 * 60 * 1000
# The vendor rejects an events request whose date range exceeds 190 days.
VENDOR_MAX_EVENT_RANGE_MS = 190 * DAY_MS


def _event_windows_requested(requests: list[RecordedRequest]) -> list[tuple[int, int]]:
    windows = []
    for request in requests:
        date_filter = request.param("filter")
        assert date_filter is not None
        lower, upper = date_filter.split(";")
        assert lower.startswith("date>=") and upper.startswith("date<")
        windows.append((int(lower.removeprefix("date>=")), int(upper.removeprefix("date<"))))
    return windows


class TestEventStreams:
    @pytest.fixture(autouse=True)
    def _frozen_now(self) -> Iterator[None]:
        with time_machine.travel(NOW, tick=False):
            yield

    @parameterized.expand(sorted(VENDOR_EVENT_DATA_KEYS.items()))
    def test_rows_are_read_from_vendor_key_with_date_converted(self, endpoint: str, data_key: str) -> None:
        result = _driver().run(
            endpoint,
            [_response(data_key, [{"eventId": "e1", "date": 1609459200000}], scrollId=None)],
            incremental_field="date",
            db_incremental_field_last_value=NOW - timedelta(days=1),
        )

        assert result.raised is None
        assert result.rows == [{"eventId": "e1", "date": datetime(2021, 1, 1, tzinfo=UTC)}]

    @parameterized.expand(
        [
            ("incremental_recent_watermark", datetime(2021, 1, 1, tzinfo=UTC), 1609459200000),
            ("incremental_watermark_older_than_max_range", datetime(2019, 6, 1, tzinfo=UTC), 1559347200000),
            ("full_refresh_backfills_history", None, NOW_MS - 730 * DAY_MS),
        ]
    )
    def test_requests_bounded_windows_covering_watermark_to_now(
        self, _name: str, last_value: Any, expected_start_ms: int
    ) -> None:
        result = _driver().run(
            "page_view_events",
            always(_response("results", [], scrollId=None)),
            incremental_field="date" if last_value is not None else None,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        windows = _event_windows_requested(result.requests)
        assert all(request.param("sort") == "date" for request in result.requests)
        assert windows[0][0] == expected_start_ms
        assert windows[-1][1] == NOW_MS
        assert all(lower < upper <= lower + VENDOR_MAX_EVENT_RANGE_MS for lower, upper in windows)
        assert all(prev[1] == nxt[0] for prev, nxt in zip(windows, windows[1:]))

    def test_resumes_mid_window_and_checkpoints_the_next_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["session_events"], "page_size", 1)
        window_start = NOW_MS - 200 * DAY_MS
        result = _driver().run(
            "session_events",
            [
                _response("sessionInitializedEvents", [], scrollId=None),
                _response("sessionInitializedEvents", [], scrollId=None),
            ],
            resume_state=GainsightPxResumeConfig(scroll_id="saved-cursor", window_start=window_start),
            incremental_field="date",
            db_incremental_field_last_value=datetime(2019, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("scrollId") == "saved-cursor"
        assert _event_windows_requested(result.requests)[0][0] == window_start
        assert result.requests[1].param("scrollId") is None
        assert result.saved_states == [GainsightPxResumeConfig(window_start=window_start + 180 * DAY_MS)]

    @parameterized.expand(
        [
            ("aware_datetime", datetime(2021, 1, 1, 1, tzinfo=UTC), 1609462800000),
            ("naive_datetime_is_utc", datetime(2021, 1, 1, 1), 1609462800000),
            ("epoch_millis", 1609462800000, 1609462800000),
            ("iso_string", "2021-01-01T01:00:00+00:00", 1609462800000),
        ]
    )
    def test_watermark_to_epoch_millis(self, _name: str, value: Any, expected: int) -> None:
        assert _to_epoch_millis(value) == expected


class TestSessionHardening:
    """The API key travels in a custom header the sample-capture denylist can't recognise, so the
    framework auth registers its value for redaction across errors, logs, and captured samples."""

    def test_source_registers_api_key_for_redaction(self) -> None:
        result = _driver().run("users", [_response("users", [], scrollId=None)])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("secret-key",)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_maps_status_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("key", "us") is expected

        assert network.requests_log[0].path == "/v1/accounts"
        assert network.requests_log[0].param("pageSize") == "1"
        assert network.requests_log[0].headers["x-aptrinsic-api-key"] == "key"


class TestSourceResponse:
    @parameterized.expand(
        [
            ("accounts", ["id"], "createDate"),
            ("users", ["id"], "createDate"),
            ("features", ["id"], None),
            ("segments", ["id"], None),
            ("engagements", ["id"], None),
            ("articles", ["id"], "createdDate"),
            ("kc_bots", ["id"], "createdDate"),
            ("session_events", ["eventId"], "date"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        data_key = GAINSIGHT_PX_ENDPOINTS[endpoint].data_key
        result = _driver().run(endpoint, always(_response(data_key, [], isLastPage=True, scrollId=None)))
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
