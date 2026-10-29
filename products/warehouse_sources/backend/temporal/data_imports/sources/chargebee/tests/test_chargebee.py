from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.chargebee.chargebee import (
    ChargebeePaginator,
    ChargebeeResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chargebee.source import ChargebeeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chargebee import (
    ChargebeeSourceConfig,
)


class TestChargebeePaginator:
    def test_update_state_empty_body(self) -> None:
        paginator = ChargebeePaginator()
        response = MagicMock()
        response.json.return_value = {}
        paginator.update_state(response)
        assert paginator._next_offset is None
        assert paginator.has_next_page is False

    def test_get_resume_state_returns_none_on_terminal_page(self) -> None:
        paginator = ChargebeePaginator()
        response = MagicMock()
        response.json.return_value = {"list": []}
        paginator.update_state(response)

        assert paginator.get_resume_state() is None

        # has_next_page is left at its BasePaginator default (True) so a fresh run still fires the first request.


class TestChargebeeSourceResumeBehavior:
    """End-to-end resume behaviour through ``source_for_pipeline``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(ChargebeeSource(), ChargebeeSourceConfig(api_key="test-key", site_name="site-test"))

    @staticmethod
    def _page(endpoint: str, row_id: str, next_offset: str | None = None) -> ScriptedResponse:
        wrapper = {
            "CreditUnits": "credit_unit",
            "ItemPrices": "item_price",
            "PaymentSchedules": "payment_schedule",
        }.get(endpoint, endpoint[:-1].lower())
        body: dict[str, Any] = {"list": [{wrapper: {"id": row_id}}]}
        if next_offset is not None:
            body["next_offset"] = next_offset
        return ScriptedResponse(json=body)

    @pytest.mark.parametrize(
        "endpoint",
        [
            "CreditUnits",
            "Customers",
            "Events",
            "Invoices",
            "ItemPrices",
            "Items",
            "Meters",
            "Subscriptions",
            "Transactions",
            "Orders",
        ],
    )
    def test_fresh_run_saves_offset_after_each_non_terminal_page(self, endpoint: str) -> None:
        # Three pages: two with next_offset (intermediate), one terminal. Selector
        # is a list under "list" — match chargebee's actual response shape.
        result = self._driver().run(
            endpoint,
            [
                self._page(endpoint, "c1", "cursor-1"),
                self._page(endpoint, "c2", "cursor-2"),
                self._page(endpoint, "c3"),
            ],
        )

        # First request has no offset (fresh run); subsequent requests carry the prior page's cursor.
        assert result.params("offset") == [None, "cursor-1", "cursor-2"]
        assert result.raised is None
        assert result.saved_states == [
            ChargebeeResumeConfig(next_offset="cursor-1"),
            ChargebeeResumeConfig(next_offset="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        result = self._driver().run(
            "Customers",
            [self._page("Customers", "c4")],
            resume_state=ChargebeeResumeConfig(next_offset="cursor-resumed"),
        )

        assert result.params("offset") == ["cursor-resumed"]
        assert result.raised is None

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = self._driver().run("Customers", [self._page("Customers", "a")])

        assert result.params("offset") == [None]
        assert result.raised is None


class TestChargebeeSiteNameValidation:
    @pytest.mark.parametrize(
        "site_name",
        [
            # Digits are valid in a Chargebee subdomain; the site name is a DNS label. A prior
            # letters-only check rejected these before any request was made.
            "acme2024",
            "shop24",
            "acme-test",
            "acme",
        ],
    )
    def test_accepts_valid_subdomain_site_names(self, site_name: str) -> None:
        config = ChargebeeSourceConfig(api_key="key", site_name=site_name)
        with scripted_network([ScriptedResponse()]) as network:
            is_valid, message = ChargebeeSource().validate_credentials(config, team_id=1)
        assert (is_valid, message) == (True, None)
        assert [request.url for request in network.requests_log] == [
            f"https://{site_name}.chargebee.com/api/v2/customers?limit=1"
        ]
        assert network.requests_log[0].headers["authorization"] == "Basic a2V5Og=="

    @pytest.mark.parametrize(
        "site_name",
        [
            "acme.chargebee.com",
            "https://acme.chargebee.com",
            "-acme",
            "acme/live",
            "",
        ],
    )
    def test_rejects_non_subdomain_without_calling_the_api(self, site_name: str) -> None:
        config = ChargebeeSourceConfig(api_key="key", site_name=site_name)
        with scripted_network([]) as network:
            is_valid, message = ChargebeeSource().validate_credentials(config, team_id=1)
        assert is_valid is False
        assert message is not None and "chargebee.com" in message
        assert network.requests_log == []


class TestChargebeeCatalogEndpoints:
    """`Items` and `ItemPrices` carry the product catalog that `subscription_items` points at.
    `CreditUnits` and `Meters` carry the usage-based billing catalog. `Disputes`, `PaymentSchedules`
    and `Einvoices` follow the same nested shape.

    Their rows sit one level deeper than the response list, so a wrong `data_selector` or
    path yields an empty table rather than an error.
    """

    @pytest.mark.parametrize(
        ("endpoint", "path", "wrapper", "row"),
        [
            ("Items", "/v2/items", "item", {"id": "gold", "type": "plan", "metadata": {"seats": 10}}),
            (
                "ItemPrices",
                "/v2/item_prices",
                "item_price",
                {"id": "gold-USD-monthly", "item_id": "gold", "price": 1000},
            ),
            (
                "CreditUnits",
                "/v2/credit_units",
                "credit_unit",
                {"id": "ai-tokens", "status": "active", "is_unlimited": False, "overdraft_amount": "100.5"},
            ),
            (
                "Meters",
                "/v2/meters",
                "meter",
                {"id": "api-calls", "type": "simple", "query": "SELECT SUM(api_calls) FROM events"},
            ),
            (
                "Disputes",
                "/v2/disputes",
                "dispute",
                {"id": "dp_1", "transaction_id": "txn_1", "status": "in_review", "type": "chargeback"},
            ),
            (
                "PaymentSchedules",
                "/v2/payment_schedules",
                "payment_schedule",
                {"id": "ps_1", "entity_id": "inv_1", "schedule_entries": [{"id": "pse_1", "amount": 500}]},
            ),
            (
                "Einvoices",
                "/v2/einvoices",
                "einvoice",
                {"id": "einv_1", "entity_type": "credit_note", "entity_id": "cn_1", "status": "accepted"},
            ),
        ],
    )
    def test_yields_the_nested_catalog_object(
        self, endpoint: str, path: str, wrapper: str, row: dict[str, Any]
    ) -> None:
        result = SourceDriver(ChargebeeSource(), ChargebeeSourceConfig(api_key="test-key", site_name="site-test")).run(
            endpoint, [ScriptedResponse(json={"list": [{wrapper: row}]})]
        )

        assert result.paths == [f"/api{path}"]
        assert result.items == [[row]]
        assert result.raised is None


class TestChargebeeIncrementalFilter:
    """The server-side cursor filter must only be sent once a real watermark exists (#76090).

    Chargebee omits `updated_at`/`occurred_at` on some records (e.g. voided authorization
    transactions), and its API excludes those records whenever the filter param is present.
    Sending the filter with the initial value 0 on the first sync therefore drops those
    records permanently. The first incremental sync must go out unfiltered; the pipeline
    still advances the watermark from the synced rows.
    """

    CURSOR_PARAMS = {
        "Customers": "updated_at[after]",
        "Einvoices": "updated_at[after]",
        "Events": "occurred_at[after]",
        "Invoices": "updated_at[after]",
        "ItemPrices": "updated_at[after]",
        "Items": "updated_at[after]",
        "Orders": "updated_at[after]",
        "PaymentSchedules": "updated_at[after]",
        "Subscriptions": "updated_at[after]",
        "Transactions": "updated_at[after]",
    }

    def _drive(self, endpoint: str, *, incremental: bool, last_value: Any) -> DriveResult:
        driver = SourceDriver(ChargebeeSource(), ChargebeeSourceConfig(api_key="test-key", site_name="site-test"))
        return driver.run(
            endpoint,
            [ScriptedResponse(json={"list": []})],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )

    @pytest.mark.parametrize("endpoint", sorted(CURSOR_PARAMS))
    def test_first_incremental_sync_omits_cursor_filter(self, endpoint: str) -> None:
        result = self._drive(endpoint, incremental=True, last_value=None)

        assert result.requests[0].param(self.CURSOR_PARAMS[endpoint]) is None
        assert result.raised is None

    @pytest.mark.parametrize("endpoint", sorted(CURSOR_PARAMS))
    def test_incremental_sync_with_watermark_sends_cursor_filter(self, endpoint: str) -> None:
        result = self._drive(endpoint, incremental=True, last_value=1750000000)

        assert result.requests[0].param(self.CURSOR_PARAMS[endpoint]) == "1750000000"
        assert result.raised is None

    @pytest.mark.parametrize("endpoint", sorted(CURSOR_PARAMS))
    def test_full_refresh_never_sends_cursor_filter(self, endpoint: str) -> None:
        result = self._drive(endpoint, incremental=False, last_value=1750000000)

        assert result.requests[0].param(self.CURSOR_PARAMS[endpoint]) is None
        assert result.raised is None

    @pytest.mark.parametrize("endpoint", ["CreditUnits", "Disputes", "Meters"])
    def test_full_refresh_only_endpoints_ignore_incremental_watermark(self, endpoint: str) -> None:
        result = self._drive(endpoint, incremental=True, last_value=1750000000)

        assert result.queries == [{"limit": ("100",)}]
        assert result.raised is None
