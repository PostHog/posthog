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
    INSTITUTION_COUNTRY_CODES,
    OFFSET_PAGINATED_ENDPOINTS,
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


def _item(**fields) -> ScriptedResponse:
    return ScriptedResponse(json={"item": {"item_id": "item-1", **fields}})


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
    @pytest.mark.parametrize(
        "endpoint, preamble, path",
        [
            ("transactions", [], "/transactions/get"),
            ("investment_transactions", [_item(billed_products=["investments"])], "/investments/transactions/get"),
        ],
    )
    @mock.patch(f"{_MODULE}._today")
    def test_paginates_via_offset_until_total(
        self, mock_today: mock.MagicMock, endpoint: str, preamble: list[ScriptedResponse], path: str
    ) -> None:
        mock_today.return_value = "2024-06-01"
        _, rows_key, total_key = OFFSET_PAGINATED_ENDPOINTS[endpoint]
        full_page = [{"id": str(i), "date": "2024-01-01"} for i in range(PAGE_SIZE)]
        result = _driver().run(
            endpoint,
            [
                *preamble,
                ScriptedResponse(json={rows_key: full_page, total_key: PAGE_SIZE + 1}),
                ScriptedResponse(json={rows_key: [{"id": "last", "date": "2024-01-02"}], total_key: PAGE_SIZE + 1}),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.saved_states == [PlaidResumeConfig(offset=PAGE_SIZE)]
        page_requests = result.requests[len(preamble) :]
        assert [request.path for request in page_requests] == [path, path]
        bodies = [request.json() for request in page_requests]
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


class TestGetRowsProductGatedEndpoints:
    @pytest.mark.parametrize("endpoint", ["investment_holdings", "investment_transactions", "liabilities"])
    def test_skips_item_without_product(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_item(billed_products=["transactions"], products=["transactions"])])

        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/item/get"]

    @pytest.mark.parametrize(
        "error_code, should_raise",
        [
            ("NO_INVESTMENT_ACCOUNTS", False),
            ("INVALID_PRODUCT", True),
        ],
    )
    def test_product_error_handling(self, error_code: str, should_raise: bool) -> None:
        result = _driver().run(
            "investment_holdings",
            [
                _item(products=["investments"]),
                ScriptedResponse(status=400, json={"error_type": "ITEM_ERROR", "error_code": error_code}),
            ],
        )

        assert (result.raised is not None) is should_raise
        assert result.rows == []
        assert result.paths == ["/item/get", "/investments/holdings/get"]

    def test_holdings_rows(self) -> None:
        holding = {"account_id": "a1", "security_id": "s1", "quantity": 10, "cost_basis": 100.0}
        result = _driver().run(
            "investment_holdings",
            [
                _item(billed_products=["investments"]),
                ScriptedResponse(json={"holdings": [holding], "securities": [{"security_id": "s1"}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [holding]

    def test_retries_product_not_ready(self) -> None:
        result = _driver().run(
            "investment_transactions",
            [
                _item(billed_products=["investments"]),
                ScriptedResponse(status=400, json={"error_type": "ITEM_ERROR", "error_code": "PRODUCT_NOT_READY"}),
                ScriptedResponse(
                    json={
                        "investment_transactions": [{"investment_transaction_id": "t1", "date": "2024-01-01"}],
                        "total_investment_transactions": 1,
                    }
                ),
            ],
        )

        assert result.raised is None
        assert [row["investment_transaction_id"] for row in result.rows] == ["t1"]
        assert result.paths == ["/item/get", "/investments/transactions/get", "/investments/transactions/get"]

    def test_liabilities_flattened_with_type(self) -> None:
        result = _driver().run(
            "liabilities",
            [
                _item(billed_products=["liabilities"]),
                ScriptedResponse(
                    json={
                        "liabilities": {
                            "credit": [{"account_id": "c1", "aprs": []}],
                            "mortgage": [{"account_id": "m1", "interest_rate": {"percentage": 3.5}}],
                            "student": None,
                        }
                    }
                ),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"account_id": "c1", "aprs": [], "liability_type": "credit"},
            {"account_id": "m1", "interest_rate": {"percentage": 3.5}, "liability_type": "mortgage"},
        ]


class TestGetRowsInstitutions:
    def test_looks_up_item_institution(self) -> None:
        institution = {"institution_id": "ins_1", "name": "Example Bank"}
        result = _driver().run(
            "institutions",
            [_item(institution_id="ins_1"), ScriptedResponse(json={"institution": institution})],
        )

        assert result.raised is None
        assert result.rows == [institution]
        assert result.paths == ["/item/get", "/institutions/get_by_id"]
        assert result.requests[1].json() == {
            "client_id": "cid",
            "secret": "sec",
            "institution_id": "ins_1",
            "country_codes": INSTITUTION_COUNTRY_CODES,
        }

    def test_item_without_institution_yields_nothing(self) -> None:
        result = _driver().run("institutions", [_item(institution_id=None)])

        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/item/get"]


class TestPlaidSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = PLAID_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, always(ScriptedResponse(json={"item": {}})))

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if endpoint in OFFSET_PAGINATED_ENDPOINTS:
            # Newest-first ordering — watermark commits only at run end.
            assert response.sort_mode == "desc"
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["date"]
        else:
            assert response.sort_mode == "asc"
            assert response.partition_mode is None
