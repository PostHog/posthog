from datetime import UTC, datetime
from typing import Any, cast

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bigcommerce.bigcommerce import (
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
            ("products", False),
            ("categories", False),
            ("brands", False),
            ("customers", False),
            ("orders", False),
            ("products", True),
            ("categories", True),  # categories has no date_modified field: stays full refresh
            ("brands", True),  # same for brands
            ("customers", True),
            ("orders", True),
        ]
    )
    def test_write_disposition_and_incremental_param(self, name: str, should_use_incremental_field: bool) -> None:
        resource = get_resource(name, should_use_incremental_field)
        endpoint = cast(Endpoint, resource["endpoint"])
        params = cast(dict[str, Any], endpoint["params"])

        incremental_capable = name in ("products", "customers", "orders")
        use_incremental = should_use_incremental_field and incremental_capable

        if use_incremental:
            assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        else:
            assert resource["write_disposition"] == "replace"

        incremental_key = "min_date_modified" if name == "orders" else "date_modified:min"
        if use_incremental:
            assert incremental_key in params
            assert params[incremental_key]["type"] == "incremental"
        else:
            assert incremental_key not in params


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
    @pytest.mark.parametrize("status_code", [200, 401, 403, 404])
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
