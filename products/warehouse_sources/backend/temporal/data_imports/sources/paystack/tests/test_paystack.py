import json
from typing import Any

import pytest

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paystack import (
    PaystackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.paystack import (
    PAGE_SIZE,
    PaystackPaginator,
    PaystackResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.source import PaystackSource


def _meta(page: int, page_count: int) -> dict[str, Any]:
    return {"total": page_count * PAGE_SIZE, "perPage": PAGE_SIZE, "page": page, "pageCount": page_count}


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


_MID_SETTLEMENT_STATE = PaystackResumeConfig(
    fanout_state={"completed": [], "current": "/settlement/11/transactions", "child_state": {"next_page": 2}}
)


class TestPaystackPaginator:
    def test_update_state_stops_on_empty_page_without_meta(self) -> None:
        # No usable meta: fall back to Paystack's documented "stop when a page is empty" signal.
        paginator = PaystackPaginator()
        paginator.update_state(_response({"data": []}), [])
        assert paginator.has_next_page is False

    def test_get_resume_state_returns_none_on_terminal_page(self) -> None:
        paginator = PaystackPaginator(page=2)
        paginator.update_state(_response({"data": [{"id": 1}], "meta": _meta(page=2, page_count=2)}), [{"id": 1}])
        assert paginator.get_resume_state() is None


class TestValidateCredentials:
    def test_sends_bearer_header(self) -> None:
        with scripted_network([ScriptedResponse(json={"status": True})]) as network:
            assert validate_credentials("sk_test_secret") is True

        assert network.requests_log[0].headers["authorization"] == "Bearer sk_test_secret"
        assert network.requests_log[0].path == "/transaction"
        assert network.requests_log[0].param("perPage") == "1"


class TestPaystackSourceResumeBehavior:
    """End-to-end resume behaviour through the source pipeline."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(PaystackSource(), PaystackSourceConfig(secret_api_key="sk_test_x"))

    @pytest.mark.parametrize(
        "schema_name, page_size_param",
        [("Transactions", "perPage"), ("TransactionSplits", "per_page")],
    )
    def test_fresh_run_saves_next_page_after_each_non_terminal_page(
        self, schema_name: str, page_size_param: str
    ) -> None:
        responses = [
            ScriptedResponse(json={"data": [{"id": 1}], "meta": _meta(page=1, page_count=3)}),
            ScriptedResponse(json={"data": [{"id": 2}], "meta": _meta(page=2, page_count=3)}),
            ScriptedResponse(json={"data": [{"id": 3}], "meta": _meta(page=3, page_count=3)}),
        ]
        result = self._driver().run(schema_name, responses)

        assert result.raised is None
        assert result.params("page") == ["1", "2", "3"]
        assert result.params(page_size_param) == ["100", "100", "100"]
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert result.saved_states == [PaystackResumeConfig(next_page=2), PaystackResumeConfig(next_page=3)]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        result = self._driver().run(
            "Customers",
            [ScriptedResponse(json={"data": [{"id": 50}], "meta": _meta(page=5, page_count=5)})],
            resume_state=PaystackResumeConfig(next_page=5),
        )

        assert result.raised is None
        assert result.params("page") == ["5"]
        assert result.rows == [{"id": 50}]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = self._driver().run(
            "Refunds", [ScriptedResponse(json={"data": [{"id": 1}], "meta": _meta(page=1, page_count=1)})]
        )

        assert result.raised is None
        assert result.params("page") == ["1"]
        assert result.rows == [{"id": 1}]

    def test_mandate_authorizations_follow_meta_next_cursor(self) -> None:
        responses = [
            ScriptedResponse(json={"data": [{"id": 1}], "meta": {"per_page": 50, "next": "c2", "count": 1}}),
            ScriptedResponse(json={"data": [{"id": 2}], "meta": {"per_page": 50, "next": None, "count": 1}}),
        ]
        result = self._driver().run("DirectDebitMandateAuthorizations", responses)

        assert result.raised is None
        assert result.paths == ["/directdebit/mandate-authorizations"] * 2
        assert result.params("cursor") == [None, "c2"]
        assert result.params("page") == [None, None]
        assert result.rows == [{"id": 1}, {"id": 2}]
        assert result.saved_states == [PaystackResumeConfig(next_cursor="c2")]

    def test_mandate_authorizations_resume_from_saved_cursor(self) -> None:
        result = self._driver().run(
            "DirectDebitMandateAuthorizations",
            [ScriptedResponse(json={"data": [{"id": 2}], "meta": {"per_page": 50, "next": None, "count": 1}})],
            resume_state=PaystackResumeConfig(next_cursor="c2"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["c2"]
        assert result.rows == [{"id": 2}]

    def test_settlement_transactions_fan_out_per_settlement(self) -> None:
        responses = [
            ScriptedResponse(json={"data": [{"id": 11}, {"id": 12}], "meta": _meta(page=1, page_count=1)}),
            ScriptedResponse(json={"data": [{"id": 1}], "meta": _meta(page=1, page_count=2)}),
            ScriptedResponse(json={"data": [{"id": 2}], "meta": _meta(page=2, page_count=2)}),
            ScriptedResponse(json={"data": [{"id": 3}], "meta": _meta(page=1, page_count=1)}),
        ]
        result = self._driver().run("SettlementTransactions", responses)

        assert result.raised is None
        assert result.paths == [
            "/settlement",
            "/settlement/11/transactions",
            "/settlement/11/transactions",
            "/settlement/12/transactions",
        ]
        assert result.params("page") == ["1", "1", "2", "1"]
        assert result.rows == [
            {"id": 1, "settlement_id": 11},
            {"id": 2, "settlement_id": 11},
            {"id": 3, "settlement_id": 12},
        ]
        assert result.response is not None
        assert result.response.primary_keys == ["settlement_id", "id"]
        assert result.saved_states[0] == _MID_SETTLEMENT_STATE

    def test_settlement_transactions_resume_mid_settlement(self) -> None:
        responses = [
            ScriptedResponse(json={"data": [{"id": 11}, {"id": 12}], "meta": _meta(page=1, page_count=1)}),
            ScriptedResponse(json={"data": [{"id": 2}], "meta": _meta(page=2, page_count=2)}),
            ScriptedResponse(json={"data": [{"id": 3}], "meta": _meta(page=1, page_count=1)}),
        ]
        result = self._driver().run("SettlementTransactions", responses, resume_state=_MID_SETTLEMENT_STATE)

        assert result.raised is None
        assert result.paths == ["/settlement", "/settlement/11/transactions", "/settlement/12/transactions"]
        assert result.params("page") == ["1", "2", "1"]
        assert result.rows == [{"id": 2, "settlement_id": 11}, {"id": 3, "settlement_id": 12}]
