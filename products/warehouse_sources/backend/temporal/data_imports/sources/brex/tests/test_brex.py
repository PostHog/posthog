from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex import (
    BrexResumeConfig,
    _to_rfc3339,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.settings import (
    BREX_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    BrexEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.source import BrexSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.brex import BrexSourceConfig

CASH_TX_PATH = BREX_ENDPOINTS["cash_transactions"].path


def _page(items: list[dict[str, Any]], next_cursor: str | None) -> dict[str, Any]:
    return {"items": items, "next_cursor": next_cursor}


def _driver() -> SourceDriver:
    return SourceDriver(BrexSource(), BrexSourceConfig(api_key="bxt_token"))


class TestToRfc3339:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02", "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
            (1700000000, None),
        ],
    )
    def test_to_rfc3339_values(self, value, expected):
        assert _to_rfc3339(value) == expected


class TestValidateCredentials:
    def test_validate_credentials_sends_bearer_header(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("bxt_token")

        assert network.requests_log[0].headers["authorization"] == "Bearer bxt_token"


class TestGetRows:
    def test_resumes_from_saved_state(self) -> None:
        result = _driver().run(
            "users",
            [ScriptedResponse(json=_page([{"id": "u9"}], None))],
            resume_state=BrexResumeConfig(cursor="cursor-5"),
        )

        assert result.raised is None
        assert result.requests[0].param("cursor") == "cursor-5"

    def test_incremental_filter_resent_on_every_page(self) -> None:
        result = _driver().run(
            "expenses",
            [
                ScriptedResponse(json=_page([{"id": "e1"}], "cursor-2")),
                ScriptedResponse(json=_page([{"id": "e2"}], None)),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[1].param("updated_at_start") == "2024-01-02T00:00:00Z"
        assert result.requests[1].param("cursor") == "cursor-2"

    def test_429_with_unparseable_retry_after_still_retries(self) -> None:
        result = _driver().run(
            "users",
            [
                ScriptedResponse(status=429, json={}, headers={"Retry-After": "not-a-number"}),
                ScriptedResponse(json=_page([{"id": "u1"}], None)),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["u1"]
        assert len(result.requests) == 2

    def test_4xx_raises_immediately(self) -> None:
        result = _driver().run("users", [ScriptedResponse(status=401, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestGetRowsCashFanOut:
    def test_fans_out_over_cash_accounts_and_injects_account_id(self) -> None:
        result = _driver().run(
            "cash_transactions",
            [
                ScriptedResponse(json=_page([{"id": "acc_1"}, {"id": "acc_2"}], None)),
                ScriptedResponse(json=_page([{"id": "tx_1", "posted_at_date": "2024-01-01"}], None)),
                ScriptedResponse(json=_page([{"id": "tx_2", "posted_at_date": "2024-01-02"}], None)),
            ],
        )

        assert result.raised is None
        assert [(row["id"], row["account_id"]) for row in result.rows] == [("tx_1", "acc_1"), ("tx_2", "acc_2")]
        # The framework's include_from_parent key is renamed away — rows keep their old shape.
        assert all("_cash_accounts_id" not in row for row in result.rows)

        assert result.requests[0].url.split("?")[0] == "https://api.brex.com/v2/accounts/cash"
        assert result.requests[0].query == {"limit": ("100",)}
        assert result.requests[1].url.split("?")[0] == "https://api.brex.com/v2/transactions/cash/acc_1"
        assert result.requests[2].url.split("?")[0] == "https://api.brex.com/v2/transactions/cash/acc_2"

    def test_resume_skips_completed_accounts_and_uses_cursor(self) -> None:
        result = _driver().run(
            "cash_transactions",
            [
                ScriptedResponse(json=_page([{"id": "acc_1"}, {"id": "acc_2"}], None)),
                ScriptedResponse(json=_page([{"id": "tx_9"}], None)),
            ],
            resume_state=BrexResumeConfig(
                fanout_state={
                    "completed": [CASH_TX_PATH.format(account_id="acc_1")],
                    "current": CASH_TX_PATH.format(account_id="acc_2"),
                    "child_state": {"cursor": "cursor-mid"},
                }
            ),
        )

        assert result.raised is None
        assert [(row["id"], row["account_id"]) for row in result.rows] == [("tx_9", "acc_2")]
        assert len(result.requests) == 2
        assert result.requests[1].url.split("?")[0].endswith("/transactions/cash/acc_2")
        assert result.requests[1].param("cursor") == "cursor-mid"

    def test_resume_cursor_not_applied_to_other_accounts(self) -> None:
        result = _driver().run(
            "cash_transactions",
            [
                ScriptedResponse(json=_page([{"id": "acc_1"}], None)),
                ScriptedResponse(json=_page([{"id": "tx_1"}], None)),
            ],
            resume_state=BrexResumeConfig(cursor="cursor-mid", account_id="acc_gone", completed_account_ids=[]),
        )

        assert result.raised is None
        assert result.requests[1].param("cursor") is None


class TestGetRowsFieldValuesFanOut:
    def test_no_parent_field_is_injected(self) -> None:
        # Field value rows already carry field_id, so nothing is included from the parent.
        # An include_from_parent here would add a stray `_fields_brex_id` column.
        result = _driver().run(
            "field_values",
            [
                ScriptedResponse(json=_page([{"brex_id": "ef_1"}], None)),
                ScriptedResponse(json=_page([{"brex_id": "efo_1", "field_id": "ef_1"}], None)),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"brex_id": "efo_1", "field_id": "ef_1"}]


class TestBrexSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = BREX_ENDPOINTS[endpoint]
        result = _driver().run(
            endpoint, [ScriptedResponse(json=[] if endpoint == "card_accounts" else _page([], None))]
        )
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.incremental_fields:
            assert response.sort_mode == "desc"
        else:
            assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(BREX_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_dates(self, config: BrexEndpointConfig) -> None:
        # Never an updated_at-style field, which would rewrite partitions on every sync.
        if config.partition_key:
            assert config.partition_key in {"posted_at_date", "created_at"}

    def test_incremental_fields_only_declared_for_filterable_endpoints(self) -> None:
        assert set(INCREMENTAL_FIELDS.keys()) == {"card_transactions", "cash_transactions", "expenses"}
