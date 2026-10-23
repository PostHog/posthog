from datetime import UTC, date, datetime

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plaid import PlaidSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.plaid import (
    DEFAULT_START_DATE,
    PAGE_SIZE,
    PlaidResumeConfig,
    _base_url,
    _format_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.settings import ENDPOINTS, PLAID_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.source import PlaidSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.plaid.plaid"


def _driver() -> SourceDriver:
    return SourceDriver(
        PlaidSource(),
        PlaidSourceConfig(environment="production", client_id="cid", secret="sec", access_token="tok"),
    )


class TestBaseUrl:
    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil")


class TestFormatDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02"),
            (date(2024, 1, 2), "2024-01-02"),
            ("2024-01-02", "2024-01-02"),
            ("2024-01-02T03:04:05Z", "2024-01-02"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_date(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (400, False),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={})]) as network:
            assert validate_credentials("production", "cid", "sec", "tok") is expected

        assert network.requests_log[0].path == "/item/get"
        assert network.requests_log[0].json() == {"client_id": "cid", "secret": "sec", "access_token": "tok"}

    def test_validate_credentials_swallows_exceptions(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("production", "cid", "sec", "tok") is False

        assert {request.path for request in network.requests_log} == {"/item/get"}


class TestGetRowsAccounts:
    def test_accounts_single_fetch(self) -> None:
        result = _driver().run("accounts", [ScriptedResponse(json={"accounts": [{"account_id": "a1"}]})])

        assert result.raised is None
        assert result.items == [[{"account_id": "a1"}]]
        assert result.paths == ["/accounts/get"]


class TestGetRowsTransactions:
    @mock.patch(f"{_MODULE}._today")
    def test_paginates_via_offset_until_total(self, mock_today: mock.MagicMock) -> None:
        mock_today.return_value = "2024-06-01"
        full_page = [{"transaction_id": str(i), "date": "2024-01-01"} for i in range(PAGE_SIZE)]
        result = _driver().run(
            "transactions",
            [
                ScriptedResponse(json={"transactions": full_page, "total_transactions": PAGE_SIZE + 1}),
                ScriptedResponse(
                    json={
                        "transactions": [{"transaction_id": "last", "date": "2024-01-02"}],
                        "total_transactions": PAGE_SIZE + 1,
                    }
                ),
            ],
        )

        assert result.raised is None
        assert len(result.items) == 2
        assert result.saved_states == [PlaidResumeConfig(offset=PAGE_SIZE)]
        bodies = [request.json() for request in result.requests]
        assert bodies[0]["options"] == {"count": PAGE_SIZE, "offset": 0}
        assert bodies[1]["options"] == {"count": PAGE_SIZE, "offset": PAGE_SIZE}
        assert bodies[0]["start_date"] == DEFAULT_START_DATE
        assert bodies[0]["end_date"] == "2024-06-01"

    @mock.patch(f"{_MODULE}._today")
    def test_incremental_uses_watermark_as_start_date(self, mock_today: mock.MagicMock) -> None:
        mock_today.return_value = "2024-06-01"
        result = _driver().run(
            "transactions",
            [ScriptedResponse(json={"transactions": [], "total_transactions": 0})],
            incremental_field="date",
            db_incremental_field_last_value=date(2024, 5, 1),
        )

        assert result.raised is None
        body = result.requests[0].json()
        assert body["start_date"] == "2024-05-01"

    @mock.patch(f"{_MODULE}._today")
    def test_resumes_from_saved_offset(self, mock_today: mock.MagicMock) -> None:
        mock_today.return_value = "2024-06-01"
        result = _driver().run(
            "transactions",
            [ScriptedResponse(json={"transactions": [], "total_transactions": 0})],
            resume_state=PlaidResumeConfig(offset=1500),
        )

        assert result.raised is None
        body = result.requests[0].json()
        assert body["options"]["offset"] == 1500


class TestPlaidSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = PLAID_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [ScriptedResponse(json={endpoint: [], "total_transactions": 0})])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        if endpoint == "transactions":
            # Newest-first ordering — watermark commits only at run end.
            assert response.sort_mode == "desc"
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["date"]
        else:
            assert response.sort_mode == "asc"
            assert response.partition_mode is None
