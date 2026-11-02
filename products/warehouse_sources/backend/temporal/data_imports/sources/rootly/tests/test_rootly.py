from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rootly import RootlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.rootly import (
    ROOTLY_BASE_URL,
    _build_url,
    _clamp_future_value_to_now,
    _format_incremental_value,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.source import RootlySource


def _response(
    items: list[dict[str, Any]] | None, next_url: str | None = None, *, drop_data: bool = False
) -> ScriptedResponse:
    body: dict[str, Any] = {"links": {"next": next_url}}
    if not drop_data:
        body["data"] = items or []
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(RootlySource(), RootlySourceConfig(api_key="rootly_test"))


class TestBuildUrl:
    def test_no_params_returns_base(self) -> None:
        assert _build_url("https://api.rootly.com/v1/users", {}) == "https://api.rootly.com/v1/users"


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "cursor-token", "cursor-token"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestClampFutureValueToNow:
    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("cursor-token") == "cursor-token"


class TestPagination:
    def test_follows_links_next_and_flattens(self) -> None:
        second = "https://api.rootly.com/v1/incidents?page%5Bnumber%5D=2"

        result = _driver().run(
            "incidents",
            [
                _response([{"id": "1", "type": "incidents", "attributes": {"title": "A"}}], next_url=second),
                _response([{"id": "2", "type": "incidents", "attributes": {"title": "B"}}]),
            ],
        )

        assert result.rows == [
            {"id": "1", "type": "incidents", "title": "A"},
            {"id": "2", "type": "incidents", "title": "B"},
        ]
        assert result.urls[0].split("?")[0] == f"{ROOTLY_BASE_URL}/incidents"
        assert result.requests[0].param("page[size]") == "100"
        # The next-page URL is self-contained; the original params must not be re-appended.
        assert result.urls[1] == second
        assert set(result.queries[1]) == {"page[number]"}

    @parameterized.expand(
        [
            ("empty_collection", False),
            # A body without `data` is treated as an empty page (JSON:API always carries `data`).
            ("missing_data_key", True),
        ]
    )
    def test_empty_collection_yields_nothing(self, _name: str, drop_data: bool) -> None:
        result = _driver().run("incidents", [_response([], drop_data=drop_data)])

        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestIncrementalParams:
    @parameterized.expand(
        [
            (
                "incremental_endpoint_sorts_and_filters_on_watermark",
                "incidents",
                True,
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                {"page[size]": "100", "sort": "updated_at", "filter[updated_at][gt]": "2026-03-04T02:58:14+00:00"},
            ),
            (
                "incremental_first_sync_sorts_without_filter",
                "incidents",
                True,
                None,
                {"page[size]": "100", "sort": "updated_at"},
            ),
            (
                "incremental_disabled_has_no_sort_or_filter",
                "incidents",
                False,
                datetime(2026, 3, 4),
                {"page[size]": "100"},
            ),
            (
                "full_refresh_endpoint_never_sorts_or_filters",
                "users",
                True,
                datetime(2026, 3, 4, tzinfo=UTC),
                {"page[size]": "100"},
            ),
        ]
    )
    def test_initial_request_params(
        self,
        _name: str,
        endpoint: str,
        should_use_incremental_field: bool,
        last_value: Any,
        expected_params: dict[str, Any],
    ) -> None:
        inputs: dict[str, Any] = {"db_incremental_field_last_value": last_value}
        if should_use_incremental_field:
            inputs["incremental_field"] = "updated_at"

        result = _driver().run(endpoint, [_response([{"id": "1", "attributes": {}}])], **inputs)

        assert {name: values[0] for name, values in result.queries[0].items()} == expected_params


class TestProbeCredentials:
    @parameterized.expand([("ok", 200), ("unauthorized", 401), ("forbidden", 403)])
    def test_returns_status_code(self, _name: str, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]):
            assert probe_credentials("rootly_test", "incidents") == status_code
