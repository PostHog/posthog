from datetime import UTC, datetime
from typing import Any, cast

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bigcommerce.bigcommerce import (
    PAGE_SIZE,
    BigCommerceResumeConfig,
    _to_v2_timestamp,
    _to_v3_timestamp,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bigcommerce.source import BigCommerceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigcommerce import (
    BigCommerceSourceConfig,
)


class TestGetResource:
    @parameterized.expand(
        [
            ("products", "/v3/catalog/products", "data", True),
            ("categories", "/v3/catalog/categories", "data", True),
            ("brands", "/v3/catalog/brands", "data", True),
            ("customers", "/v3/customers", "data", True),
            ("orders", "/v2/orders", None, False),
            ("customer_groups", "/v2/customer_groups", None, False),
        ]
    )
    def test_path_and_envelope_per_endpoint(
        self, name: str, expected_path: str, expected_data_selector: str | None, expects_total_path: bool
    ) -> None:
        resource = get_resource(name, should_use_incremental_field=False)
        endpoint = cast(Endpoint, resource["endpoint"])

        assert endpoint["path"] == expected_path
        assert endpoint["data_selector"] == expected_data_selector
        assert resource["table_name"] == name
        assert resource["table_format"] == "delta"

        paginator = cast(PageNumberPaginator, endpoint["paginator"])
        assert paginator.page_param == "page"
        assert paginator.base_page == 1
        assert (paginator.total_path is not None) is expects_total_path

    @parameterized.expand(
        [
            (name, should_use_incremental_field, filter_param, cursor_path)
            for should_use_incremental_field in (False, True)
            for name, filter_param, cursor_path in [
                ("products", "date_modified:min", "date_modified"),
                ("customers", "date_modified:min", "date_modified"),
                ("channels", "date_modified:min", "date_modified"),
                ("orders", "min_date_modified", "date_modified"),
                ("refunds", "created:min", "created"),
                # No modification timestamp on these: they stay full refresh.
                ("categories", None, None),
                ("brands", None, None),
                ("variants", None, None),
            ]
        ]
    )
    def test_write_disposition_and_incremental_param(
        self, name: str, should_use_incremental_field: bool, filter_param: str | None, cursor_path: str | None
    ) -> None:
        resource = get_resource(name, should_use_incremental_field)
        endpoint = cast(Endpoint, resource["endpoint"])
        params = cast(dict[str, Any], endpoint["params"])
        incremental_params = {key: value for key, value in params.items() if isinstance(value, dict)}

        if should_use_incremental_field and filter_param is not None:
            assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
            assert list(incremental_params) == [filter_param]
            assert incremental_params[filter_param]["type"] == "incremental"
            assert incremental_params[filter_param]["cursor_path"] == cursor_path
        else:
            assert resource["write_disposition"] == "replace"
            assert incremental_params == {}


class TestTimestampConverters:
    @parameterized.expand(
        [
            ("naive", datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            ("aware_utc", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
        ]
    )
    def test_to_v3_timestamp_formats_datetime(self, _label: str, value: datetime, expected: str) -> None:
        assert _to_v3_timestamp(value) == expected

    def test_to_v3_timestamp_passes_through_non_datetime(self) -> None:
        assert _to_v3_timestamp("already-a-string") == "already-a-string"

    @parameterized.expand(
        [
            ("naive", datetime(2024, 1, 2, 3, 4, 5), "Tue, 02 Jan 2024 03:04:05 +0000"),
            ("aware_utc", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "Tue, 02 Jan 2024 03:04:05 +0000"),
        ]
    )
    def test_to_v2_timestamp_formats_datetime(self, _label: str, value: datetime, expected: str) -> None:
        assert _to_v2_timestamp(value) == expected

    def test_to_v2_timestamp_passes_through_non_datetime(self) -> None:
        assert _to_v2_timestamp("already-a-string") == "already-a-string"


def _v3_page(items: list[dict[str, Any]], current_page: int, total_pages: int) -> dict[str, Any]:
    return {
        "data": items,
        "meta": {"pagination": {"current_page": current_page, "total_pages": total_pages}},
    }


class TestBigCommerceSourceResumeBehavior:
    """End-to-end resume behaviour through ``source_for_pipeline``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(
            BigCommerceSource(), BigCommerceSourceConfig(store_hash="store123", access_token="test-token")
        )

    def test_v3_fresh_run_pages_until_total_pages_reached(self) -> None:
        result = self._driver().run(
            "products",
            [
                ScriptedResponse(json=_v3_page([{"id": 1}], current_page=1, total_pages=3)),
                ScriptedResponse(json=_v3_page([{"id": 2}], current_page=2, total_pages=3)),
                ScriptedResponse(json=_v3_page([{"id": 3}], current_page=3, total_pages=3)),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2", "3"]
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert result.saved_states == [
            BigCommerceResumeConfig(page=2),
            BigCommerceResumeConfig(page=3),
        ]

    def test_v2_orders_stops_on_empty_page_with_no_pagination_envelope(self) -> None:
        result = self._driver().run(
            "orders",
            [
                ScriptedResponse(json=[{"id": 1}]),
                ScriptedResponse(json=[{"id": 2}]),
                ScriptedResponse(json=[]),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2", "3"]
        assert result.rows == [{"id": 1}, {"id": 2}]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        result = self._driver().run(
            "customers",
            [ScriptedResponse(json=_v3_page([{"id": 9}], current_page=5, total_pages=5))],
            resume_state=BigCommerceResumeConfig(page=5),
        )

        assert result.raised is None
        assert result.params("page") == ["5"]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = self._driver().run(
            "categories", [ScriptedResponse(json=_v3_page([{"id": 1}], current_page=1, total_pages=1))]
        )

        assert result.raised is None
        assert result.params("page") == ["1"]

    def test_v3_incremental_param_carries_converted_timestamp(self) -> None:
        last_value = datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC)
        result = self._driver().run(
            "products",
            [ScriptedResponse(json=_v3_page([], current_page=1, total_pages=1))],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.requests[0].param("date_modified:min") == "2024-05-06T07:08:09Z"

    def test_order_transactions_fan_out_over_every_order(self) -> None:
        result = self._driver().run(
            "order_transactions",
            [
                ScriptedResponse(json=[{"id": 101}, {"id": 102}, {"id": 103}]),
                ScriptedResponse(json={"data": [{"id": 1, "order_id": 101}, {"id": 2, "order_id": 101}], "meta": {}}),
                # Order deleted after the order listing was read.
                ScriptedResponse(status=404, json={"status": 404, "title": "Order not found"}),
                ScriptedResponse(status=204),
                ScriptedResponse(json=[]),
            ],
        )

        assert result.raised is None
        assert [request.path for request in result.requests] == [
            "/stores/store123/v2/orders",
            "/stores/store123/v3/orders/101/transactions",
            "/stores/store123/v3/orders/102/transactions",
            "/stores/store123/v3/orders/103/transactions",
            "/stores/store123/v2/orders",
        ]
        assert result.params("page") == ["1", None, None, None, "2"]
        assert [(row["order_id"], row["id"]) for row in result.rows] == [(101, 1), (101, 2)]
        assert result.saved_states == [
            BigCommerceResumeConfig(page=1, order_index=1),
            BigCommerceResumeConfig(page=1, order_index=2),
            BigCommerceResumeConfig(page=1, order_index=3),
        ]

    def test_order_transactions_resume_skips_completed_orders(self) -> None:
        result = self._driver().run(
            "order_transactions",
            [
                ScriptedResponse(json=[{"id": 101}, {"id": 102}]),
                ScriptedResponse(json={"data": [{"id": 3, "order_id": 102}], "meta": {}}),
                ScriptedResponse(json=[]),
            ],
            resume_state=BigCommerceResumeConfig(page=4, order_index=1),
        )

        assert result.raised is None
        assert [request.path for request in result.requests] == [
            "/stores/store123/v2/orders",
            "/stores/store123/v3/orders/102/transactions",
            "/stores/store123/v2/orders",
        ]
        assert result.params("page") == ["4", None, "5"]
        assert result.rows == [{"id": 3, "order_id": 102}]

    @parameterized.expand([("order_products", "products"), ("order_shipments", "shipments")])
    def test_v2_order_children_page_until_short_page(self, endpoint: str, child_path: str) -> None:
        full_page = [{"id": child_id, "order_id": 101} for child_id in range(PAGE_SIZE)]
        result = self._driver().run(
            endpoint,
            [
                ScriptedResponse(json=[{"id": 101}, {"id": 102}, {"id": 103}]),
                ScriptedResponse(json=full_page),
                ScriptedResponse(json=[{"id": PAGE_SIZE, "order_id": 101}]),
                ScriptedResponse(status=204),
                # Order deleted after the order listing was read.
                ScriptedResponse(
                    status=404, json=[{"status": 404, "message": "The requested resource was not found."}]
                ),
                ScriptedResponse(json=[]),
            ],
        )

        assert result.raised is None
        assert [request.path for request in result.requests] == [
            "/stores/store123/v2/orders",
            f"/stores/store123/v2/orders/101/{child_path}",
            f"/stores/store123/v2/orders/101/{child_path}",
            f"/stores/store123/v2/orders/102/{child_path}",
            f"/stores/store123/v2/orders/103/{child_path}",
            "/stores/store123/v2/orders",
        ]
        assert result.params("page") == ["1", "1", "2", "1", "1", "2"]
        assert [row["id"] for row in result.rows] == list(range(PAGE_SIZE + 1))
        assert result.saved_states == [BigCommerceResumeConfig(page=1, order_index=i) for i in (1, 2, 3)]

    def test_order_statuses_is_read_in_one_request(self) -> None:
        statuses = [{"id": 0, "name": "Incomplete"}, {"id": 1, "name": "Pending"}]
        result = self._driver().run(
            "order_statuses",
            # The endpoint ignores `page`, so a second request would return the same rows again.
            [ScriptedResponse(json=statuses), ScriptedResponse(json=statuses)],
        )

        assert result.raised is None
        assert [request.path for request in result.requests] == ["/stores/store123/v2/order_statuses"]
        assert result.params("page") == [None]
        assert result.rows == statuses

    def test_refunds_stop_on_empty_page_without_pagination_meta(self) -> None:
        last_value = datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC)
        result = self._driver().run(
            "refunds",
            [
                ScriptedResponse(json={"data": [{"id": 1}], "meta": {}}),
                ScriptedResponse(json={"data": [], "meta": {}}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.requests[0].param("created:min") == "2024-05-06T07:08:09Z"
        assert result.rows == [{"id": 1}]

    def test_v2_incremental_param_carries_rfc2822_timestamp(self) -> None:
        last_value = datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC)
        result = self._driver().run(
            "orders",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.requests[0].param("min_date_modified") == "Mon, 06 May 2024 07:08:09 +0000"


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [403, 404])
    def test_returns_status_code(self, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("store123", "token") == status_code

        assert network.requests_log[0].path == "/stores/store123/v3/catalog/products"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["x-auth-token"] == "token"

    def test_returns_none_on_connection_error(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("store123", "token") is None

        assert {request.path for request in network.requests_log} == {"/stores/store123/v3/catalog/products"}
