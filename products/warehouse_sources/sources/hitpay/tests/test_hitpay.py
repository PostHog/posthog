from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hitpay import HitpaySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.hitpay import (
    HitpayResumeConfig,
    _format_date_filter,
    _paginator_for,
    base_url_for_environment,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.settings import (
    HITPAY_ENDPOINTS,
    RECURRING_BILLING_STATUSES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.source import HitpaySource


class TestBaseUrlForEnvironment:
    @parameterized.expand(
        [
            ("production", "production", "https://api.hit-pay.com"),
            ("sandbox", "sandbox", "https://api.sandbox.hit-pay.com"),
            ("none_defaults_to_production", None, "https://api.hit-pay.com"),
            ("unknown_defaults_to_production", "staging", "https://api.hit-pay.com"),
        ]
    )
    def test_base_url(self, _name: str, environment: str | None, expected: str) -> None:
        assert base_url_for_environment(environment) == expected


class TestFormatDateFilter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "1970-01-01", "1970-01-01"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_date_filter(value) == expected


class TestPaginatorFor:
    def test_single_endpoint_gets_single_page_paginator(self) -> None:
        assert isinstance(_paginator_for(HITPAY_ENDPOINTS["RecurringBilling"]), SinglePagePaginator)


def _driver(platform_api_key: str | None = None) -> SourceDriver:
    return SourceDriver(
        HitpaySource(), HitpaySourceConfig(api_key="key", platform_api_key=platform_api_key, environment="production")
    )


def _response(items: list[dict[str, Any]], *, extra: dict[str, Any] | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items}
    if extra:
        body.update(extra)
    return ScriptedResponse(json=body)


class TestHitpaySourcePageNumberEndpoint:
    def test_paginates_until_last_page(self) -> None:
        result = _driver().run(
            "SubscriptionPlans",
            [
                _response([{"id": "1"}, {"id": "2"}], extra={"meta": {"last_page": 2}}),
                _response([{"id": "3"}], extra={"meta": {"last_page": 2}}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert result.paths == ["/v1/subscription-plan", "/v1/subscription-plan"]
        assert result.params("page") == ["1", "2"]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "SubscriptionPlans",
            [_response([{"id": "2"}], extra={"meta": {"last_page": 2}})],
            resume_state=HitpayResumeConfig(next_page=2),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["2"]
        assert result.params("page") == ["2"]


class TestHitpaySourceCursorEndpoint:
    def test_paginates_via_cursor(self) -> None:
        result = _driver().run(
            "Charges",
            [
                _response([{"id": "1"}], extra={"meta": {"next_cursor": "abc"}}),
                _response([{"id": "2"}], extra={"meta": {"next_cursor": None}}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert result.paths == ["/v1/charges", "/v1/charges"]
        assert result.params("cursor") == [None, "abc"]

    @parameterized.expand(
        [
            ("charges", "Charges", "created_at", "/v1/charges", "date_from"),
            (
                "balance_transactions",
                "BalanceTransactions",
                "datetime",
                "/v1/balances/adyen/transactions",
                "created_at_from",
            ),
        ]
    )
    def test_incremental_date_filter_sent_when_enabled(
        self, _name: str, endpoint: str, incremental_field: str, expected_path: str, expected_param: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": "1"}], extra={"meta": {"next_cursor": None}})],
            incremental_field=incremental_field,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.paths == [expected_path]
        assert result.params(expected_param) == ["2026-03-04"]


class TestRecurringBillingFanOut:
    def test_requests_every_status_and_concatenates_rows(self) -> None:
        result = _driver(platform_api_key="platform-key").run(
            "RecurringBilling", [_response([{"id": status}]) for status in RECURRING_BILLING_STATUSES]
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == list(RECURRING_BILLING_STATUSES)
        assert result.paths == ["/v1/recurring-billing"] * len(RECURRING_BILLING_STATUSES)
        assert result.params("status") == list(RECURRING_BILLING_STATUSES)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("unreachable", None, False, "Could not connect to HitPay"),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        status_code: int | None,
        expected_valid: bool,
        expected_message_snippet: str | None,
    ) -> None:
        script = always(ConnectionError("boom")) if status_code is None else [ScriptedResponse(status=status_code)]
        with scripted_network(script) as network:
            is_valid, message = validate_credentials("key", None, "production")

        assert {request.path for request in network.requests_log} == {"/v1/account-status"}
        assert network.requests_log[0].headers["x-business-api-key"] == "key"
        assert is_valid is expected_valid
        if expected_message_snippet is None:
            assert message is None
        else:
            assert expected_message_snippet in (message or "")
