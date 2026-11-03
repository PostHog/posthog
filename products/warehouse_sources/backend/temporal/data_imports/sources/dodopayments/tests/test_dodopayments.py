from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.dodopayments import (
    DodoPaymentsResumeConfig,
    to_iso8601,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.settings import (
    DODOPAYMENTS_ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.source import DodoPaymentsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dodopayments import (
    DodoPaymentsSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(DodoPaymentsSource(), DodoPaymentsSourceConfig(api_key="test-api-key", mode="live"))


def _response(items: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"items": items})


def _page(size: int, start: int = 0) -> ScriptedResponse:
    return _response([{"payment_id": f"pay_{start + i}", "created_at": "2024-05-01T00:00:00Z"} for i in range(size)])


class TestToIso8601:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            # A datetime watermark must not be str()'d: "2024-05-01 10:00:00+00:00" is not
            # ISO-8601 and the date filters reject it.
            (datetime(2024, 5, 1, 10, tzinfo=UTC), "2024-05-01T10:00:00Z"),
            (datetime(2024, 5, 1, 10), "2024-05-01T10:00:00Z"),
            (datetime(2024, 5, 1, 12, tzinfo=UTC).astimezone(UTC), "2024-05-01T12:00:00Z"),
            (date(2024, 5, 1), "2024-05-01T00:00:00Z"),
            ("2024-05-01T10:00:00Z", "2024-05-01T10:00:00Z"),
            ("2024-05-01T12:00:00+02:00", "2024-05-01T10:00:00Z"),
            (1714557600, "2024-05-01T10:00:00Z"),
            ("not-a-date", None),
            (object(), None),
        ],
    )
    def test_values(self, value, expected):
        assert to_iso8601(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "mode, expected_url",
        [
            ("live", "https://live.dodopayments.com/customers?page_size=1"),
            ("test", "https://test.dodopayments.com/customers?page_size=1"),
        ],
    )
    def test_probe_targets_the_host_for_the_mode(self, mode: str, expected_url: str) -> None:
        # A live key probed against the test host (or vice versa) always 401s, so the mode has to
        # reach the probe URL.
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("key", mode) == (True, 200)

        assert network.requests_log[0].url == expected_url
        assert network.requests_log[0].headers["authorization"] == "Bearer key"


class TestPagination:
    def test_full_page_then_empty_page_terminates(self) -> None:
        result = _driver().run("payments", [_page(PAGE_SIZE), _page(0)])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE
        assert result.params("page_number") == ["0", "1"]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run("payments", [_page(2, start=400)], resume_state=DodoPaymentsResumeConfig(page_number=4))

        assert result.raised is None
        assert [row["payment_id"] for row in result.rows] == ["pay_400", "pay_401"]
        assert result.params("page_number") == ["4"]


class TestRequestParams:
    @pytest.mark.parametrize(
        "endpoint, expected_param",
        [
            ("payments", "created_at_gte"),
            ("subscriptions", "created_at_gte"),
            ("balance_ledger_entries", "created_at_gte"),
            # Usage events filter on `start`, not `created_at_gte`.
            ("events", "start"),
        ],
    )
    def test_incremental_sync_sends_the_endpoints_date_filter(self, endpoint: str, expected_param: str) -> None:
        result = _driver().run(
            endpoint,
            [_page(1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, 10, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param(expected_param) == "2024-05-01T10:00:00Z"

    def test_unparseable_watermark_drops_the_filter(self) -> None:
        # Sending a value the API rejects would fail the whole sync; a full walk is the safe fallback.
        result = _driver().run(
            "payments", [_page(1)], should_use_incremental_field=True, db_incremental_field_last_value="garbage"
        )

        assert result.raised is None
        assert result.requests[0].param("created_at_gte") is None

    def test_catalog_endpoint_never_gets_a_date_filter(self) -> None:
        # `/products` exposes no date filter; sending one would be rejected.
        result = _driver().run(
            "products",
            [_response([{"product_id": "prod_1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert set(result.requests[0].query) == {"page_size", "page_number"}


class TestSourceResponseMetadata:
    def test_framework_incremental_injection_is_not_used(self) -> None:
        # The date filter is baked into the request params, so letting the framework inject its own
        # incremental param too would send a second, differently named filter.
        result = _driver().run(
            "payments",
            [_page(1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert set(result.requests[0].query) == {"page_size", "page_number", "created_at_gte"}


class TestEndpointCatalog:
    def test_every_incremental_endpoint_declares_a_server_side_filter(self):
        # Without a server-side filter an "incremental" sync would still fetch every page. A fan-out
        # child is filtered through its parent listing instead.
        for name, config in DODOPAYMENTS_ENDPOINTS.items():
            if not config.incremental_fields:
                continue
            filter_config = (
                DODOPAYMENTS_ENDPOINTS[config.fanout.parent_name]
                if config.fanout and config.start_param is None
                else config
            )
            assert filter_config.start_param is not None, name

    def test_incremental_cursor_matches_the_partition_key(self):
        # The cursor and the partition key must both be creation timestamps that never change.
        for name, config in DODOPAYMENTS_ENDPOINTS.items():
            if not config.incremental_fields:
                continue
            assert [f["field"] for f in config.incremental_fields] == [config.partition_key], name


class TestFanout:
    @pytest.mark.parametrize(
        "endpoint, parent_row, child_path, child_row, expected_row",
        [
            (
                "payment_line_items",
                {"payment_id": "pay_1", "created_at": "2024-05-01T00:00:00Z", "currency": "USD", "status": "ok"},
                "/payments/pay_1/line-items",
                {"items_id": "pdt_1", "amount": 1000, "tax": 0, "refundable_amount": 1000},
                {
                    "items_id": "pdt_1",
                    "amount": 1000,
                    "tax": 0,
                    "refundable_amount": 1000,
                    "payment_id": "pay_1",
                    "payment_created_at": "2024-05-01T00:00:00Z",
                    "currency": "USD",
                },
            ),
            (
                "subscription_usage_history",
                {"subscription_id": "sub_1", "created_at": "2024-05-01T00:00:00Z"},
                "/subscriptions/sub_1/usage-history",
                {"start_date": "2024-05-01T00:00:00Z", "end_date": "2024-06-01T00:00:00Z", "meters": []},
                {
                    "start_date": "2024-05-01T00:00:00Z",
                    "end_date": "2024-06-01T00:00:00Z",
                    "meters": [],
                    "subscription_id": "sub_1",
                },
            ),
            (
                "payout_breakup_details",
                {"payout_id": "po_1", "created_at": "2024-05-01T00:00:00Z"},
                "/payouts/po_1/breakup/details",
                {"id": "ble_1", "event_type": "payment", "payout_currency_amount": 500},
                {"id": "ble_1", "event_type": "payment", "payout_currency_amount": 500, "payout_id": "po_1"},
            ),
            (
                "credit_entitlement_balances",
                {"id": "cde_1", "name": "Credits"},
                "/credit-entitlements/cde_1/balances",
                {"id": "bal_1", "credit_entitlement_id": "cde_1", "customer_id": "cus_1", "balance": "10"},
                {"id": "bal_1", "credit_entitlement_id": "cde_1", "customer_id": "cus_1", "balance": "10"},
            ),
            (
                "customer_emails",
                {"customer_id": "cus_1", "created_at": "2024-05-01T00:00:00Z"},
                "/customers/cus_1/emails",
                {"email_log_id": "eml_1", "email_type": "payment_successful", "status": "delivered"},
                {
                    "email_log_id": "eml_1",
                    "email_type": "payment_successful",
                    "status": "delivered",
                    "customer_id": "cus_1",
                },
            ),
            (
                "customer_wallets",
                {"customer_id": "cus_1", "created_at": "2024-05-01T00:00:00Z"},
                "/customers/cus_1/wallets",
                {"customer_id": "cus_1", "currency": "USD", "balance": 500},
                {"customer_id": "cus_1", "currency": "USD", "balance": 500},
            ),
            (
                "customer_wallet_ledger_entries",
                {"customer_id": "cus_1", "created_at": "2024-05-01T00:00:00Z"},
                "/customers/cus_1/wallets/ledger-entries",
                {"id": "cwt_1", "customer_id": "cus_1", "currency": "USD", "amount": 250, "is_credit": True},
                {"id": "cwt_1", "customer_id": "cus_1", "currency": "USD", "amount": 250, "is_credit": True},
            ),
            # The parent field is the entitlement's own `id`, bound into a path placeholder also named `id`.
            (
                "entitlement_grants",
                {"id": "ent_1", "name": "Pro license"},
                "/entitlements/ent_1/grants",
                {"id": "grant_1", "entitlement_id": "ent_1", "customer_id": "cus_1", "status": "Delivered"},
                {"id": "grant_1", "entitlement_id": "ent_1", "customer_id": "cus_1", "status": "Delivered"},
            ),
        ],
    )
    def test_child_is_read_per_parent_with_parent_fields(
        self,
        endpoint: str,
        parent_row: dict[str, Any],
        child_path: str,
        child_row: dict[str, Any],
        expected_row: dict[str, Any],
    ) -> None:
        result = _driver().run(endpoint, [_response([parent_row]), _response([child_row])])

        assert result.raised is None
        parent_path = "/" + child_path.split("/")[1]
        assert result.paths == [parent_path, child_path]
        assert result.rows == [expected_row]

    @pytest.mark.parametrize(
        "endpoint, parent_row, expected_parent_filter, expected_child_query",
        [
            # Line items is a single object, not a page, and filters through the payment listing.
            (
                "payment_line_items",
                {"payment_id": "pay_1", "created_at": "2024-05-01T00:00:00Z", "currency": "USD"},
                "2024-05-01T10:00:00Z",
                set(),
            ),
            # Usage history has no incremental field, so its parent listing stays unfiltered.
            ("subscription_usage_history", {"subscription_id": "sub_1"}, None, {"page_size", "page_number"}),
        ],
    )
    def test_incremental_child_filters_the_parent_listing(
        self,
        endpoint: str,
        parent_row: dict[str, Any],
        expected_parent_filter: str | None,
        expected_child_query: set[str],
    ) -> None:
        result = _driver().run(
            endpoint,
            [_response([parent_row]), _response([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, 10, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("created_at_gte") == expected_parent_filter
        assert set(result.requests[1].query) == expected_child_query

    @pytest.mark.parametrize(
        "endpoint, should_use_incremental_field, expected_child_filter",
        [
            # The ledger filters its own requests, so the parent listings stay unfiltered.
            ("credit_entitlement_ledger", True, "2024-05-01T10:00:00Z"),
            ("credit_entitlement_grants", False, None),
        ],
    )
    def test_customer_credit_child_binds_both_ids_from_each_balance(
        self, endpoint: str, should_use_incremental_field: bool, expected_child_filter: str | None
    ) -> None:
        child = endpoint.removeprefix("credit_entitlement_")
        result = _driver().run(
            endpoint,
            [
                _response([{"id": "cde_1"}]),
                _response(
                    [
                        {"id": "bal_1", "credit_entitlement_id": "cde_1", "customer_id": "cus_1"},
                        {"id": "bal_2", "credit_entitlement_id": "cde_1", "customer_id": "cus_2"},
                    ]
                ),
                _response([{"id": "row_1", "credit_entitlement_id": "cde_1", "customer_id": "cus_1"}]),
                _response([{"id": "row_2", "credit_entitlement_id": "cde_1", "customer_id": "cus_2"}]),
            ],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=datetime(2024, 5, 1, 10, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.paths == [
            "/credit-entitlements",
            "/credit-entitlements/cde_1/balances",
            f"/credit-entitlements/cde_1/balances/cus_1/{child}",
            f"/credit-entitlements/cde_1/balances/cus_2/{child}",
        ]
        assert [set(request.query) for request in result.requests[:2]] == [{"page_size", "page_number"}] * 2
        assert [request.param("start_date") for request in result.requests[2:]] == [expected_child_filter] * 2
        assert [row["id"] for row in result.rows] == ["row_1", "row_2"]

    def test_paginated_child_walks_every_page_of_each_parent(self) -> None:
        def periods(count: int, prefix: str) -> ScriptedResponse:
            return _response([{"start_date": f"{prefix}{i}", "meters": []} for i in range(count)])

        result = _driver().run(
            "subscription_usage_history",
            [
                _response([{"subscription_id": "sub_1"}, {"subscription_id": "sub_2"}]),
                periods(PAGE_SIZE, "a"),
                periods(1, "b"),
                periods(1, "c"),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/subscriptions",
            "/subscriptions/sub_1/usage-history",
            "/subscriptions/sub_1/usage-history",
            "/subscriptions/sub_2/usage-history",
        ]
        assert result.params("page_number") == ["0", "0", "1", "0"]
        assert len(result.rows) == PAGE_SIZE + 2
        assert result.rows[-1] == {"start_date": "c0", "meters": [], "subscription_id": "sub_2"}

    def test_missing_parent_is_skipped(self) -> None:
        # A payment removed between the listing and its child request must not fail the table.
        result = _driver().run(
            "payment_line_items",
            [
                _response(
                    [
                        {"payment_id": "pay_gone", "created_at": "2024-05-01T00:00:00Z", "currency": "USD"},
                        {"payment_id": "pay_2", "created_at": "2024-05-02T00:00:00Z", "currency": "EUR"},
                    ]
                ),
                ScriptedResponse(status=404, json={"message": "not found"}),
                _response([{"items_id": "pdt_1", "amount": 1}]),
            ],
        )

        assert result.raised is None
        assert [(row["payment_id"], row["currency"]) for row in result.rows] == [("pay_2", "EUR")]

    def test_resume_skips_parents_already_synced(self) -> None:
        result = _driver().run(
            "payout_breakup_details",
            [
                _response([{"payout_id": "po_1"}, {"payout_id": "po_2"}]),
                _response([{"id": "ble_2"}]),
            ],
            resume_state=DodoPaymentsResumeConfig(completed=["/payouts/po_1/breakup/details"]),
        )

        assert result.raised is None
        assert result.paths == ["/payouts", "/payouts/po_2/breakup/details"]
        assert result.rows == [{"id": "ble_2", "payout_id": "po_2"}]
        assert result.final_state == DodoPaymentsResumeConfig(
            completed=["/payouts/po_1/breakup/details", "/payouts/po_2/breakup/details"]
        )
