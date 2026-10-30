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
    @pytest.mark.parametrize(
        "endpoint, path, partition_field, partition_value",
        [
            ("payments", "payments", "createdAt", "2025-03-01T10:00:00+00:00"),
            ("payouts", "payouts", "createdAt", "2026-05-04T08:30:00+00:00"),
            # Invoices carry only date fields, no createdAt.
            ("invoices", "invoices", "issuedAt", "2025-02-01"),
        ],
    )
    def test_paginates_via_hal_next_link(
        self, endpoint: str, path: str, partition_field: str, partition_value: str
    ) -> None:
        next_url = f"https://api.mollie.com/v2/{path}?from=obj_next&limit=250"
        result = _driver().run(
            endpoint,
            [
                _response(
                    endpoint,
                    [
                        {"id": "obj_1", partition_field: partition_value},
                        {"id": "obj_2", partition_field: partition_value},
                    ],
                    next_url=next_url,
                ),
                _response(endpoint, [{"id": "obj_3", partition_field: partition_value}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["obj_1", "obj_2", "obj_3"]
        assert result.paths[0] == f"/v2/{path}"
        assert result.response is not None
        assert all(row[key] for row in result.rows for key in result.response.partition_keys or [])
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


# Each payment carries amountCaptured, so the captures fan-out keeps every parent.
_CAPTURABLE = {"amountCaptured": {"currency": "EUR", "value": "10.00"}}


class TestFanOut:
    @pytest.mark.parametrize(
        "endpoint, parent_key, child_key, parent_id_column, parent_path, child_suffix, parent_extra",
        [
            ("mandates", "customers", "mandates", "customerId", "customers", "mandates", {}),
            ("captures", "payments", "captures", "paymentId", "payments", "captures", _CAPTURABLE),
            ("settlement_payments", "settlements", "payments", "settlementId", "settlements", "payments", {}),
        ],
    )
    def test_walks_every_parent_and_carries_parent_id(
        self,
        endpoint: str,
        parent_key: str,
        child_key: str,
        parent_id_column: str,
        parent_path: str,
        child_suffix: str,
        parent_extra: dict[str, Any],
    ) -> None:
        child_next = f"https://api.mollie.com/v2/{parent_path}/p_1/{child_suffix}?from=c_2&limit=250"
        result = _driver().run(
            endpoint,
            [
                _response(parent_key, [{"id": "p_1", **parent_extra}, {"id": "p_2", **parent_extra}]),
                _response(child_key, [{"id": "c_1"}], next_url=child_next),
                _response(child_key, [{"id": "c_2"}]),
                _response(child_key, [{"id": "c_3"}]),
            ],
        )

        assert result.raised is None
        assert [(r[parent_id_column], r["id"]) for r in result.rows] == [
            ("p_1", "c_1"),
            ("p_1", "c_2"),
            ("p_2", "c_3"),
        ]
        assert all(f"_{parent_key}_id" not in r for r in result.rows)
        assert result.response is not None
        assert result.response.primary_keys == [parent_id_column, "id"]
        assert result.paths[1] == f"/v2/{parent_path}/p_1/{child_suffix}"
        assert result.urls[2] == child_next
        assert result.paths[3] == f"/v2/{parent_path}/p_2/{child_suffix}"
        last_state = result.saved_states[-1]
        assert last_state.next_url is None
        assert last_state.fanout_state["completed"] == [
            f"/{parent_path}/p_1/{child_suffix}",
            f"/{parent_path}/p_2/{child_suffix}",
        ]

    @pytest.mark.parametrize(
        "payments, expected_paths",
        [
            # Payments whose method does not support captures carry no amountCaptured.
            (
                [{"id": "tr_1"}, {"id": "tr_2", **_CAPTURABLE}, {"id": "tr_3", "amountCaptured": None}],
                ["/v2/payments", "/v2/payments/tr_2/captures"],
            ),
            # A zero amountCaptured still means the payment supports captures, which can be pending.
            (
                [{"id": "tr_1", "amountCaptured": {"currency": "EUR", "value": "0.00"}}],
                ["/v2/payments", "/v2/payments/tr_1/captures"],
            ),
            ([{"id": "tr_1"}, {"id": "tr_2"}], ["/v2/payments"]),
        ],
    )
    def test_captures_skip_payments_without_capture_support(
        self, payments: list[dict[str, Any]], expected_paths: list[str]
    ) -> None:
        responses = [_response("payments", payments)]
        responses += [_response("captures", [{"id": f"cpt_{i}"}]) for i in range(len(expected_paths) - 1)]
        result = _driver().run("captures", responses)

        assert result.raised is None
        assert result.paths == expected_paths
        assert len(result.rows) == len(expected_paths) - 1

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
