from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gocardless import (
    GoCardlessSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless import (
    GoCardlessResumeConfig,
    _base_url,
    _format_created_at,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.settings import (
    ENDPOINTS,
    GOCARDLESS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.source import GoCardlessSource


def _page(data_key: str, items: list[dict[str, Any]], after: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={data_key: items, "meta": {"cursors": {"before": None, "after": after}, "limit": 500}})


def _driver() -> SourceDriver:
    return SourceDriver(GoCardlessSource(), GoCardlessSourceConfig(environment="live", access_token="token"))


class TestBaseUrl:
    def test_invalid_environment_raises(self) -> None:
        with pytest.raises(ValueError):
            _base_url("evil.example.com")


class TestFormatCreatedAt:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, 123000, tzinfo=UTC), "2024-01-02T03:04:05.123Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05.000Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00.000Z"),
            ("2024-01-02T03:04:05.000Z", "2024-01-02T03:04:05.000Z"),
        ],
    )
    def test_format_values(self, value: Any, expected: str) -> None:
        assert _format_created_at(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("live", "token") is expected

        assert network.requests_log[0].path == "/customers"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer token"
        assert network.requests_log[0].headers["gocardless-version"] == "2015-07-06"

    def test_validate_credentials_rejects_bad_environment_without_request(self) -> None:
        with scripted_network([]) as network:
            assert validate_credentials("evil", "token") is False

        assert network.requests_log == []


class TestPagination:
    def test_paginates_via_meta_cursors(self) -> None:
        result = _driver().run(
            "payments",
            [
                _page("payments", [{"id": "PM1"}], after="PM1"),
                _page("payments", [{"id": "PM2"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["PM1", "PM2"]
        assert result.params("limit") == ["500", "500"]
        assert result.params("after") == [None, "PM1"]
        # Checkpoint saved after the first page (points at the next cursor); the null cursor ends it.
        assert result.saved_states == [GoCardlessResumeConfig(after="PM1")]

    def test_incremental_request_includes_filter(self) -> None:
        result = _driver().run(
            "events",
            [_page("events", [{"id": "EV1"}])],
            incremental_field="created_at",
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("created_at[gte]") == "2024-01-02T00:00:00.000Z"

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "payments",
            [_page("payments", [{"id": "PM9"}])],
            resume_state=GoCardlessResumeConfig(after="PM_RESUME"),
        )

        assert result.raised is None
        assert result.requests[0].param("after") == "PM_RESUME"


class TestFanout:
    @pytest.mark.parametrize(
        "endpoint, parent_key, parent_id, resolve_param, injected_key",
        [
            ("payout_items", "payouts", "PO1", "payout", "payout_id"),
            ("balances", "creditors", "CR1", "creditor", "creditor_id"),
        ],
    )
    def test_child_is_fetched_per_parent_with_parent_id_injected(
        self, endpoint: str, parent_key: str, parent_id: str, resolve_param: str, injected_key: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _page(parent_key, [{"id": parent_id}]),
                _page(endpoint, [{"type": "a", "amount": "1"}], after="X1"),
                _page(endpoint, [{"type": "b", "amount": "2"}]),
            ],
        )

        assert result.raised is None
        assert result.paths[1] == f"/{endpoint}"
        assert result.requests[1].param(resolve_param) == parent_id
        assert result.requests[1].param("value_date_from") is None
        assert result.requests[2].param("after") == "X1"
        assert [row["type"] for row in result.rows] == ["a", "b"]
        assert all(row[injected_key] == parent_id for row in result.rows)

    @time_machine.travel(datetime(2026, 3, 31, 23, 30, tzinfo=UTC), tick=False)
    def test_payment_account_transactions_are_fetched_per_account_with_value_date_range(self) -> None:
        result = _driver().run(
            "payment_account_transactions",
            [
                _page("payment_accounts", [{"id": "BA1"}]),
                _page("payment_account_transactions", [{"id": "PATR1"}], after="PATR1"),
                _page("payment_account_transactions", [{"id": "PATR2"}]),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/payment_accounts",
            "/payment_accounts/BA1/transactions",
            "/payment_accounts/BA1/transactions",
        ]
        assert result.params("value_date_from") == [None, "2015-01-01", "2015-01-01"]
        assert result.params("value_date_to") == [None, "2026-04-01", "2026-04-01"]
        assert result.requests[2].param("after") == "PATR1"
        assert [(row["id"], row["payment_account_id"]) for row in result.rows] == [("PATR1", "BA1"), ("PATR2", "BA1")]

    def test_balances_lists_every_creditor(self) -> None:
        result = _driver().run("balances", [_page("creditors", [{"id": "CR1"}]), _page("balances", [])])

        assert result.raised is None
        assert result.requests[0].param("created_at[gte]") is None


class TestGoCardlessSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = GOCARDLESS_ENDPOINTS[endpoint]
        parent_key = config.fanout.parent_name if config.fanout is not None else endpoint
        result = _driver().run(endpoint, [_page(parent_key, [])])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ([config.primary_key] if config.primary_key else None)
        if config.partition_key is None:
            assert response.partition_keys is None
            return
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        # Lists are reverse-chronological; only the incremental events stream
        # declares desc so the pipeline defers its watermark commit.
        if config.incremental_fields:
            assert response.sort_mode == "desc"
        else:
            assert response.sort_mode == "asc"
