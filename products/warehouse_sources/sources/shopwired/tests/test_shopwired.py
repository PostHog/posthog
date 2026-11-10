from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.sources.sdk.testing import RecordedRequest, ScriptedResponse, SourceDriver, always
from products.warehouse_sources.sources.shopwired._config import ShopWiredSourceConfig
from products.warehouse_sources.sources.shopwired.settings import PAGE_SIZE
from products.warehouse_sources.sources.shopwired.shopwired import ShopWiredResumeConfig, to_unix_timestamp
from products.warehouse_sources.sources.shopwired.source import ShopWiredSource


def _driver() -> SourceDriver:
    return SourceDriver(ShopWiredSource(), ShopWiredSourceConfig(api_key="sw-key", api_secret="sw-secret"))


def _full_page(start_id: int) -> list[dict[str, Any]]:
    return [{"id": start_id + i} for i in range(PAGE_SIZE)]


class TestPagination:
    @parameterized.expand(
        [
            ("products", "/v1/products", None),
            ("transactions", "/v1/shopwired-payments/transactions", "created_asc"),
            ("payouts", "/v1/shopwired-payments/payouts", "created_asc"),
        ]
    )
    def test_paginates_and_progresses_offset(self, endpoint: str, path: str, sort: str | None) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=_full_page(0)), ScriptedResponse(json=[{"id": 999}])])

        assert result.raised is None
        assert result.paths == [path, path]
        assert result.params("sort") == [sort, sort]
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.rows[-1] == {"id": 999}
        # count/offset are ShopWired's pagination params (limit_param="count").
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("count")[0] == str(PAGE_SIZE)
        # Checkpoint saved once after the full first page (points at the next page); short page ends it.
        assert result.saved_states == [ShopWiredResumeConfig(offset=PAGE_SIZE, from_timestamp=None)]

    @parameterized.expand([("orders",), ("incomplete_orders",)])
    def test_resumes_from_saved_offset_and_pinned_window(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=[{"id": 5}])],
            resume_state=ShopWiredResumeConfig(offset=200, from_timestamp=1700000000),
            should_use_incremental_field=True,
            # A watermark that advanced mid-run must not replace the pinned window from resume state.
            db_incremental_field_last_value=datetime(2024, 6, 1, tzinfo=UTC),
        )

        assert result.rows == [{"id": 5}]
        assert result.params("offset") == ["200"]
        assert result.params("from") == ["1700000000"]


class TestIncrementalRequests:
    @parameterized.expand(
        [
            ("orders", False),
            ("orders", True),
            ("incomplete_orders", False),
            ("incomplete_orders", True),
        ]
    )
    def test_creation_filter_and_sort(self, endpoint: str, incremental: bool) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=[{"id": 1, "created": "2024-01-02T00:00:00Z"}])],
            incremental_field="created",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.rows == [{"id": 1, "created": "2024-01-02T00:00:00Z"}]
        assert result.paths == [f"/v1/{endpoint.replace('_', '-')}"]
        assert result.params("from") == ["1704067200" if incremental else None]
        assert result.params("sort") == ["date"]


class TestProductVariations:
    def test_walks_products_and_keeps_all_variations_with_parent_ids(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v1/products":
                return ScriptedResponse(json=_full_page(0) if request.param("offset") == "0" else [{"id": 100}])
            if request.path == "/v1/products/0/variations":
                return ScriptedResponse(json=[*_full_page(0), {"id": 100}])
            if request.path == "/v1/products/100/variations":
                return ScriptedResponse(json=[{"id": 0, "sku": "example-sku"}])
            return ScriptedResponse(json=[])

        result = _driver().run("product_variations", respond)

        assert result.raised is None
        assert len(result.rows) == 102
        assert result.rows[:101] == [{"id": i, "product_id": 0} for i in range(101)]
        assert result.rows[-1] == {"id": 0, "sku": "example-sku", "product_id": 100}
        parents = [request for request in result.requests if request.path == "/v1/products"]
        assert [request.param("offset") for request in parents] == ["0", "100"]
        assert [request.param("count") for request in parents] == ["100", "100"]
        children = [request for request in result.requests if request.path.endswith("/variations")]
        assert len(children) == 101
        assert all(not request.query for request in children)

    def test_resumes_after_a_completed_product(self) -> None:
        interrupted = _driver().run(
            "product_variations",
            [
                ScriptedResponse(json=[{"id": 11}, {"id": 22}]),
                ScriptedResponse(json=[{"id": 1}]),
                ScriptedResponse(status=403, json={"error": "Forbidden"}),
            ],
        )

        assert isinstance(interrupted.raised, HTTPError)
        assert interrupted.rows == [{"id": 1, "product_id": 11}]
        assert interrupted.final_state is not None
        resumed = _driver().run(
            "product_variations",
            [ScriptedResponse(json=[{"id": 11}, {"id": 22}]), ScriptedResponse(json=[{"id": 1}])],
            resume_state=interrupted.final_state,
        )

        assert resumed.raised is None
        assert resumed.paths == ["/v1/products", "/v1/products/22/variations"]
        assert resumed.rows == [{"id": 1, "product_id": 22}]


class TestErrorClassification:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise(self, _name: str, status: int) -> None:
        # 4xx is permanent — it must surface (not retry, not silently sync 0 rows).
        result = _driver().run("products", [ScriptedResponse(status=status, json={"error": "nope"})])

        assert isinstance(result.raised, HTTPError)
        assert len(result.requests) == 1

    @parameterized.expand([("server_error", 500), ("service_unavailable", 503), ("rate_limited", 429)])
    def test_retryable_statuses_are_retried_then_succeed(self, _name: str, status: int) -> None:
        result = _driver().run(
            "products", [ScriptedResponse(status=status, json={}), ScriptedResponse(json=[{"id": 1}])]
        )

        assert result.rows == [{"id": 1}]
        assert len(result.requests) == 2


class TestToUnixTimestamp:
    @parameterized.expand(
        [
            ("none", None, None),
            ("datetime", datetime(2024, 1, 1, tzinfo=UTC), 1704067200),
            # Naive values must be treated as UTC regardless of the worker's local timezone.
            ("naive_datetime", datetime(2024, 1, 1), 1704067200),
            ("date", date(2024, 1, 1), 1704067200),
            ("epoch_int", 1704067200, 1704067200),
            ("epoch_float", 1704067200.5, 1704067200),
            ("rfc2822_string", "Mon, 01 Jan 2024 00:00:00 +0000", 1704067200),
            ("iso_string", "2024-01-01T00:00:00+00:00", 1704067200),
            ("naive_iso_string", "2024-01-01T00:00:00", 1704067200),
            ("unparseable_string", "not-a-date-at-all-99", None),
            ("empty_string", "", None),
            ("bool", True, None),
        ]
    )
    def test_conversion(self, _name: str, value: Any, expected: int | None) -> None:
        assert to_unix_timestamp(value) == expected


class TestShopWiredSourceResponse:
    @parameterized.expand([("products",), ("orders",), ("order_statuses",), ("vouchers",)])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _driver().run(endpoint, always(ScriptedResponse(json=[]))).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_count == 1
        assert response.partition_size == 1
