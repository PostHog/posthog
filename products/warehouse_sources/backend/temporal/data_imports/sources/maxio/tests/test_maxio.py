from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.maxio import MaxioSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.maxio import (
    MaxioPaginator,
    MaxioResumeConfig,
    format_start_datetime,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.source import MaxioSource


def _customer_page(count: int, start_id: int = 1) -> list[dict[str, Any]]:
    return [{"customer": {"id": start_id + i, "created_at": "2024-01-01T00:00:00Z"}} for i in range(count)]


def _resource(endpoint_name: str, should_use_incremental_field: bool) -> dict[str, Any]:
    # get_resource returns an EndpointResource TypedDict whose nested values are unions;
    # cast to a plain dict so the structural assertions below stay readable.
    return cast(dict[str, Any], get_resource(endpoint_name, should_use_incremental_field=should_use_incremental_field))


class TestConverters:
    def test_format_start_datetime_passes_through_initial_string(self) -> None:
        assert format_start_datetime("1970-01-01 00:00:00") == "1970-01-01 00:00:00"


class TestMaxioPaginator:
    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = MaxioPaginator(page_size=2)
        paginator.update_state(MagicMock(), data=[{"id": 1}])

        assert paginator.get_resume_state() is None


class TestGetResource:
    @pytest.mark.parametrize(
        "endpoint",
        [
            "products",
            "product_families",
            "coupons",
            "components",
            "payment_profiles",
            "credit_notes",
            "component_price_points",
            "product_price_points",
        ],
    )
    def test_full_refresh_only_endpoints_never_get_incremental_params(self, endpoint: str) -> None:
        # These endpoints advertise no incremental fields; even if the pipeline asked for
        # incremental, no server-side filter params must be emitted.
        resource = _resource(endpoint, should_use_incremental_field=True)
        params = resource["endpoint"]["params"]

        assert "date_field" not in params
        assert "start_datetime" not in params
        assert "since_id" not in params


class TestMaxioSourceDrive:
    """Run Maxio extraction through its pipeline entry point."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(MaxioSource(), MaxioSourceConfig(subdomain="acme", api_key="test-key", region="us"))

    def test_paginates_and_saves_state_after_each_non_terminal_page(self) -> None:
        result = self._driver().run(
            "customers",
            [
                ScriptedResponse(json=_customer_page(PAGE_SIZE)),
                ScriptedResponse(json=_customer_page(1, start_id=PAGE_SIZE + 1)),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.params("per_page") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # Rows are unwrapped from the `{"customer": {...}}` envelope by the data selector.
        assert result.items[0][0] == {"id": 1, "created_at": "2024-01-01T00:00:00Z"}
        assert result.saved_states == [MaxioResumeConfig(endpoint="customers", next_page=2)]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        result = self._driver().run(
            "customers",
            [ScriptedResponse(json=_customer_page(1))],
            resume_state=MaxioResumeConfig(endpoint="customers", next_page=5),
        )

        assert result.raised is None
        assert result.params("page") == ["5"]

    @pytest.mark.parametrize(
        ("endpoint", "body", "expected_row"),
        [
            (
                "subscriptions",
                [{"subscription": {"id": 1, "updated_at": "2024-05-02T00:00:00Z"}}],
                {"id": 1, "updated_at": "2024-05-02T00:00:00Z"},
            ),
            (
                "subscription_components",
                {"subscriptions_components": [{"id": 7, "subscription_id": 1, "component_id": 7}]},
                {"id": 7, "subscription_id": 1, "component_id": 7},
            ),
        ],
    )
    def test_incremental_run_sends_formatted_watermark(
        self, endpoint: str, body: Any, expected_row: dict[str, Any]
    ) -> None:
        result = self._driver().run(
            endpoint,
            [ScriptedResponse(json=body)],
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2024, 5, 1, 10, 30, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.items[0][0] == expected_row
        assert result.requests[0].param("date_field") == "updated_at"
        assert result.requests[0].param("start_datetime") == "2024-05-01 10:30:00"
        assert result.requests[0].param("sort") == "updated_at"
        assert result.requests[0].param("direction") == "asc"

    def test_incremental_events_run_sends_since_id(self) -> None:
        result = self._driver().run(
            "events",
            [ScriptedResponse(json=[{"event": {"id": 101, "key": "signup_success"}}])],
            incremental_field="id",
            db_incremental_field_last_value=100,
        )

        assert result.raised is None
        assert result.requests[0].param("since_id") == "100"
        assert result.items[0][0]["id"] == 101


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_error_fragment"),
        [
            (404, False, "site not found"),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_error_fragment: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, error = validate_credentials("key", "acme", "us")

        assert {request.path for request in network.requests_log} == {"/customers.json"}
        assert network.requests_log[0].path == "/customers.json"
        assert network.requests_log[0].param("page") == "1"
        assert network.requests_log[0].param("per_page") == "1"
        assert valid is expected_valid
        if expected_error_fragment is None:
            assert error is None
        else:
            assert error is not None
            assert expected_error_fragment in error
