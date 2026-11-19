from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.sources.maxio._config import MaxioSourceConfig
from products.warehouse_sources.sources.maxio.maxio import (
    MaxioPaginator,
    MaxioResumeConfig,
    format_start_datetime,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.sources.maxio.settings import PAGE_SIZE
from products.warehouse_sources.sources.maxio.source import MaxioSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


def _customer_page(count: int, start_id: int = 1) -> list[dict[str, Any]]:
    return [{"customer": {"id": start_id + i, "created_at": "2024-01-01T00:00:00Z"}} for i in range(count)]


def _site_components(*rows: tuple[int, int, str]) -> dict[str, Any]:
    return {
        "subscriptions_components": [
            {"id": component_id, "subscription_id": subscription_id, "component_id": component_id, "kind": kind}
            for subscription_id, component_id, kind in rows
        ]
    }


MIXED_KIND_COMPONENTS = _site_components(
    (1, 10, "metered_component"),
    (1, 11, "quantity_based_component"),
    (2, 12, "on_off_component"),
    (3, 13, "prepaid_usage_component"),
    (4, 14, "event_based_component"),
)


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

    @pytest.mark.parametrize(
        ("endpoint", "body", "expected_change_status_flag"),
        [
            ("events", [{"event": {"id": 101, "key": "signup_success"}}], None),
            ("invoice_events", {"events": [{"id": 101, "event_type": "apply_payment"}], "page": 1}, "true"),
        ],
    )
    def test_incremental_events_run_sends_since_id(
        self, endpoint: str, body: Any, expected_change_status_flag: str | None
    ) -> None:
        result = self._driver().run(
            endpoint,
            [ScriptedResponse(json=body)],
            incremental_field="id",
            db_incremental_field_last_value=100,
        )

        assert result.raised is None
        assert result.requests[0].param("since_id") == "100"
        assert result.requests[0].param("with_change_invoice_status") == expected_change_status_flag
        assert result.items[0][0]["id"] == 101


class TestMaxioFanoutDrive:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(MaxioSource(), MaxioSourceConfig(subdomain="acme", api_key="test-key", region="us"))

    @pytest.mark.parametrize(
        ("endpoint", "child_key", "expected_pairs", "expected_per_page"),
        [
            ("subscription_component_usages", "usage", [(1, 10), (3, 13)], str(PAGE_SIZE)),
            (
                "subscription_component_allocations",
                "allocation",
                [(1, 11), (2, 12), (3, 13)],
                None,
            ),
        ],
    )
    def test_fans_out_only_over_supported_component_kinds(
        self, endpoint: str, child_key: str, expected_pairs: list[tuple[int, int]], expected_per_page: str | None
    ) -> None:
        child_suffix = endpoint.rsplit("_", 1)[-1]
        first_row = {child_key: {"quantity": 3, "timestamp": "2024-02-28T09:31:05Z"}}
        result = self._driver().run(
            endpoint,
            [
                ScriptedResponse(json=MIXED_KIND_COMPONENTS),
                ScriptedResponse(json=[first_row]),
                *[ScriptedResponse(json=[]) for _ in expected_pairs[1:]],
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/subscriptions_components.json",
            *[f"/subscriptions/{sub}/components/{comp}/{child_suffix}.json" for sub, comp in expected_pairs],
        ]
        assert result.params("per_page")[1:] == [expected_per_page] * len(expected_pairs)
        # The child row omitted its ids, so it takes them from the parent row, with no parent-prefixed keys left.
        sub, comp = expected_pairs[0]
        assert result.rows == [
            {"quantity": 3, "timestamp": "2024-02-28T09:31:05Z", "subscription_id": sub, "component_id": comp}
        ]

    def test_child_rows_keep_their_own_ids(self) -> None:
        result = self._driver().run(
            "subscription_component_usages",
            [
                ScriptedResponse(json=_site_components((1, 10, "metered_component"))),
                ScriptedResponse(json=[{"usage": {"id": 5, "subscription_id": 99, "component_id": 98}}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 5, "subscription_id": 99, "component_id": 98}]

    def test_deleted_subscription_404_does_not_stop_the_fan_out(self) -> None:
        result = self._driver().run(
            "subscription_component_usages",
            [
                ScriptedResponse(json=_site_components((1, 10, "metered_component"), (2, 10, "metered_component"))),
                ScriptedResponse(status=404, json={"errors": ["Not Found"]}),
                ScriptedResponse(json=[{"usage": {"id": 7, "subscription_id": 2, "component_id": 10}}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [7]

    @pytest.mark.parametrize(
        ("incremental_inputs", "expected_since_date"),
        [
            ({}, None),
            (
                {
                    "incremental_field": "created_at",
                    "db_incremental_field_last_value": datetime(2024, 5, 1, 23, 30, 0, tzinfo=UTC),
                },
                "2024-05-01",
            ),
        ],
    )
    def test_usages_window_only_the_child_requests(
        self, incremental_inputs: dict[str, Any], expected_since_date: str | None
    ) -> None:
        result = self._driver().run(
            "subscription_component_usages",
            [
                ScriptedResponse(json=_site_components((1, 10, "metered_component"))),
                ScriptedResponse(json=[{"usage": {"id": 5, "created_at": "2024-05-02T00:00:00Z"}}]),
            ],
            **incremental_inputs,
        )

        assert result.raised is None
        # The parent listing must stay complete, or the fan-out would skip pairs with new usages.
        parent, child = result.requests
        assert parent.param("start_datetime") is None
        assert parent.param("since_date") is None
        assert child.param("since_date") == expected_since_date

    def test_resume_continues_the_parent_listing_from_the_saved_page(self) -> None:
        result = self._driver().run(
            "subscription_component_usages",
            [
                ScriptedResponse(json=_site_components((5, 10, "metered_component"))),
                ScriptedResponse(json=[]),
            ],
            resume_state=MaxioResumeConfig(
                endpoint="subscription_component_usages",
                fanout_state={"completed": [], "current": None, "child_state": None, "parent": {"page": 3}},
            ),
        )

        assert result.raised is None
        assert result.paths[0] == "/subscriptions_components.json"
        assert result.params("page")[0] == "3"


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
