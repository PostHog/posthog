from datetime import UTC, datetime
from typing import Any, Optional

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.autumn import (
    AutumnResumeConfig,
    _build_request_body,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.settings import AUTUMN_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.source import AutumnSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.autumn import AutumnSourceConfig

WATERMARK_MS = 1704067200000


class TestBuildRequestBody:
    @pytest.mark.parametrize(
        ("api_version", "endpoint", "should_use_incremental_field", "incremental_field", "last_value", "expected"),
        [
            ("2.3.0", "Customers", False, None, None, {"limit": 100}),
            ("2.3.0", "Events", False, None, None, {"limit": 1000}),
            ("2.3.0", "Invoices", False, None, None, {"limit": 500}),
            # First incremental sync has no watermark yet — no custom_range.
            ("2.3.0", "Events", True, "timestamp", None, {"limit": 1000}),
            (
                "2.3.0",
                "Events",
                True,
                "timestamp",
                WATERMARK_MS,
                {"limit": 1000, "custom_range": {"start": WATERMARK_MS}},
            ),
            # The user's chosen incremental field is honored — an unknown field is not
            # silently mapped onto the timestamp filter.
            ("2.3.0", "Events", True, "created_at", WATERMARK_MS, {"limit": 1000}),
            # Only events.list supports the server-side time filter.
            ("2.3.0", "Customers", True, "created_at", WATERMARK_MS, {"limit": 100}),
            ("2.3.0", "Coupons", False, None, None, {}),
            # 2.4.0 rejects list limits above 200; smaller page sizes pass through unchanged.
            ("2.4.0", "Customers", False, None, None, {"limit": 100}),
            ("2.4.0", "Events", False, None, None, {"limit": 200}),
            ("2.4.0", "Invoices", False, None, None, {"limit": 200}),
            (
                "2.4.0",
                "Events",
                True,
                "timestamp",
                WATERMARK_MS,
                {"limit": 200, "custom_range": {"start": WATERMARK_MS}},
            ),
            ("2.4.0", "Coupons", False, None, None, {}),
        ],
    )
    def test_body_shape(
        self,
        api_version: str,
        endpoint: str,
        should_use_incremental_field: bool,
        incremental_field: Optional[str],
        last_value: Optional[Any],
        expected: dict[str, Any],
    ) -> None:
        body = _build_request_body(
            AUTUMN_ENDPOINTS[endpoint],
            api_version,
            should_use_incremental_field,
            incremental_field,
            last_value,
        )
        assert body == expected

    def test_datetime_watermark_is_coerced_to_epoch_ms(self) -> None:
        body = _build_request_body(
            AUTUMN_ENDPOINTS["Events"],
            "2.3.0",
            True,
            "timestamp",
            datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert body["custom_range"] == {"start": WATERMARK_MS}


class TestAutumnSourceBehavior:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(AutumnSource(), AutumnSourceConfig(api_key="am_sk_test"))

    def test_fresh_run_pages_with_body_cursor_and_saves_state_after_each_page(self) -> None:
        responses = [
            ScriptedResponse(json={"list": [{"id": "cus_1"}], "next_cursor": "cursor-1"}),
            ScriptedResponse(json={"list": [{"id": "cus_2"}], "next_cursor": "cursor-2"}),
            ScriptedResponse(json={"list": [{"id": "cus_3"}], "next_cursor": None}),
        ]
        result = self._driver().run("Customers", responses, api_version="2.3.0")
        sent_bodies = [request.json() for request in result.requests]

        assert [body.get("start_cursor") for body in sent_bodies] == [None, "cursor-1", "cursor-2"]
        assert all(body["limit"] == 100 for body in sent_bodies)
        assert [row["id"] for row in result.rows] == ["cus_1", "cus_2", "cus_3"]
        assert result.saved_states == [
            AutumnResumeConfig(next_cursor="cursor-1"),
            AutumnResumeConfig(next_cursor="cursor-2"),
        ]
        assert result.raised is None

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._driver().run(
            "Customers",
            [ScriptedResponse(json={"list": [{"id": "cus_4"}], "next_cursor": None})],
            resume_state=AutumnResumeConfig(next_cursor="cursor-resumed"),
            api_version="2.3.0",
        )

        assert [request.json().get("start_cursor") for request in result.requests] == ["cursor-resumed"]
        assert [row["id"] for row in result.rows] == ["cus_4"]
        assert result.raised is None

    def test_incremental_events_run_carries_custom_range_on_every_page(self) -> None:
        responses = [
            ScriptedResponse(json={"list": [{"id": "evt_1", "timestamp": 1}], "next_cursor": "cursor-1"}),
            ScriptedResponse(json={"list": [{"id": "evt_2", "timestamp": 2}], "next_cursor": None}),
        ]
        result = self._driver().run(
            "Events",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=WATERMARK_MS,
            incremental_field="timestamp",
            api_version="2.3.0",
        )

        assert len(result.requests) == 2
        assert all(request.json()["custom_range"] == {"start": WATERMARK_MS} for request in result.requests)
        assert result.raised is None

    @pytest.mark.parametrize(
        ("endpoint", "selector", "row_id"),
        [
            ("Coupons", "coupons", "coupon_1"),
            ("FeatureGrants", "feature_grants", "grant_1"),
        ],
    )
    def test_single_page_endpoints_issue_one_request_and_select_their_root_array(
        self, endpoint: str, selector: str, row_id: str
    ) -> None:
        payload = {"coupons": [{"id": "coupon_1"}], "feature_grants": [{"id": "grant_1"}]}
        result = self._driver().run(
            endpoint,
            [ScriptedResponse(json=payload)],
            api_version="2.3.0",
        )

        assert len(result.requests) == 1
        assert result.requests[0].json() == {}
        assert result.rows == payload[selector]
        assert [row["id"] for row in result.rows] == [row_id]
        assert result.saved_states == []
        assert result.raised is None

    @pytest.mark.parametrize(
        ("api_version", "expected_limit"),
        [
            ("2.3.0", 1000),
            ("2.4.0", 200),
        ],
    )
    def test_pinned_version_reaches_the_request(self, api_version: str, expected_limit: int) -> None:
        result = self._driver().run(
            "Events", [ScriptedResponse(json={"list": [], "next_cursor": None})], api_version=api_version
        )

        assert [request.headers["x-api-version"] for request in result.requests] == [api_version]
        assert [request.json()["limit"] for request in result.requests] == [expected_limit]
        assert result.raised is None

    @pytest.mark.parametrize(
        ("endpoint", "expected_primary_keys", "expected_sort_mode"),
        [
            ("Customers", ["id"], "asc"),
            ("Events", ["id"], "desc"),
            # Entity ids are only unique within their parent customer.
            ("Entities", ["customer_id", "id"], "asc"),
        ],
    )
    def test_source_response_keys_and_sort_mode(
        self, endpoint: str, expected_primary_keys: list[str], expected_sort_mode: str
    ) -> None:
        result = self._driver().run(endpoint, [ScriptedResponse(json={"list": [], "next_cursor": None})])

        assert result.response is not None
        assert result.response.primary_keys == expected_primary_keys
        assert result.response.sort_mode == expected_sort_mode
        assert result.raised is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "api_version"),
        [
            (200, True, "2.3.0"),
            (200, True, "2.4.0"),
            (401, False, "2.3.0"),
            (403, False, "2.3.0"),
            (500, False, "2.3.0"),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool, api_version: str) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={})]) as network:
            valid, error = validate_credentials("am_sk_test", api_version)

        assert valid is expected_valid
        assert (error is None) is expected_valid
        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.method == "POST"
        assert request.path == "/v1/customers.list"
        assert request.headers["authorization"] == "Bearer am_sk_test"
        assert request.headers["x-api-version"] == api_version
        assert request.json() == {"limit": 1}
