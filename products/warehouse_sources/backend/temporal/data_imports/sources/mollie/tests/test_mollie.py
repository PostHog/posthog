from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mollie import MollieSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie import (
    MollieResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.source import MollieSource


def _driver() -> SourceDriver:
    return SourceDriver(MollieSource(), MollieSourceConfig(api_key="live_key"))


def _response(embedded_key: str, items: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"count": len(items), "_embedded": {embedded_key: items}, "_links": {}}
    if next_url:
        body["_links"]["next"] = {"href": next_url}
    return ScriptedResponse(json=body)


class TestPagination:
    def test_paginates_via_hal_next_link(self) -> None:
        next_url = "https://api.mollie.com/v2/payments?from=tr_next&limit=250"
        result = _driver().run(
            "payments",
            [
                _response("payments", [{"id": "tr_1"}, {"id": "tr_2"}], next_url=next_url),
                _response("payments", [{"id": "tr_3"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["tr_1", "tr_2", "tr_3"]
        # The next link is self-contained — the second request targets it directly.
        assert result.urls[1] == next_url
        # Checkpoint saved once after the first page (points at the next link); the short
        # final page (no next link) ends the run without another save.
        assert result.saved_states == [MollieResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_state(self) -> None:
        resume_url = "https://api.mollie.com/v2/payments?from=tr_resume&limit=250"
        result = _driver().run(
            "payments",
            [_response("payments", [{"id": "tr_9"}])],
            resume_state=MollieResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        # The saved next link becomes the first request; its self-contained query replaces the base params.
        assert result.urls == [resume_url]
        assert result.queries == [{"from": ("tr_resume",), "limit": ("250",)}]

    def test_missing_embedded_block_yields_nothing(self) -> None:
        # A 200 body without an `_embedded` block is a legitimate empty page, not an error.
        result = _driver().run("payments", [ScriptedResponse(json={"count": 0, "_links": {}})])

        assert result.raised is None
        assert result.rows == []


class TestFanOut:
    def test_mandates_walk_every_customer_and_carry_customer_id(self) -> None:
        child_next = "https://api.mollie.com/v2/customers/cst_1/mandates?from=mdt_2&limit=250"
        result = _driver().run(
            "mandates",
            [
                _response("customers", [{"id": "cst_1"}, {"id": "cst_2"}]),
                _response("mandates", [{"id": "mdt_1"}], next_url=child_next),
                _response("mandates", [{"id": "mdt_2"}]),
                _response("mandates", [{"id": "mdt_3"}]),
            ],
        )

        assert result.raised is None
        assert [(r["customerId"], r["id"]) for r in result.rows] == [
            ("cst_1", "mdt_1"),
            ("cst_1", "mdt_2"),
            ("cst_2", "mdt_3"),
        ]
        assert all("_customers_id" not in r for r in result.rows)
        assert result.response is not None
        assert result.response.primary_keys == ["customerId", "id"]
        assert result.paths[1] == "/v2/customers/cst_1/mandates"
        assert result.urls[2] == child_next
        assert result.paths[3] == "/v2/customers/cst_2/mandates"
        last_state = result.saved_states[-1]
        assert last_state.next_url is None
        assert last_state.fanout_state["completed"] == ["/customers/cst_1/mandates", "/customers/cst_2/mandates"]

    def test_resume_skips_balances_already_finished(self) -> None:
        result = _driver().run(
            "balance_transactions",
            [
                _response("balances", [{"id": "bal_1"}, {"id": "bal_2"}]),
                _response("balance_transactions", [{"id": "baltr_9"}]),
            ],
            resume_state=MollieResumeConfig(
                fanout_state={"completed": ["/balances/bal_1/transactions"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert [(r["balanceId"], r["id"]) for r in result.rows] == [("bal_2", "baltr_9")]
        assert len(result.requests) == 2
        assert result.paths[1] == "/v2/balances/bal_2/transactions"


class TestRetries:
    def test_non_retryable_4xx_raises_immediately(self) -> None:
        result = _driver().run("payments", [ScriptedResponse(status=403, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # Org access tokens 4xx without a profileId but are still valid keys.
            (400, True),
            (403, True),
            (401, False),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            valid = validate_credentials("live_key")

        assert valid is expected
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/v2/payments"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer live_key"
        assert network.session_options[0]["redact_values"] == ("live_key",)
