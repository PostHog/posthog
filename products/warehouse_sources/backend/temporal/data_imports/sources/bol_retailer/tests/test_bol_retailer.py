from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.bol_retailer.bol_retailer import (
    BolRetailerResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bol_retailer.source import BolRetailerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bolretailer import (
    BolRetailerSourceConfig,
)

TOKEN = ScriptedResponse(json={"access_token": "tok", "token_type": "Bearer", "expires_in": 299})
EMPTY = ScriptedResponse(json={})


def _run(endpoint: str, api_path: str, responses: list[ScriptedResponse], **inputs: Any) -> DriveResult:
    config = BolRetailerSourceConfig(client_id="bol_id", client_secret="bol_secret")
    script = route({"/token": [TOKEN], api_path: responses})
    return SourceDriver(BolRetailerSource(), config).run(endpoint, script, **inputs)


def _api(result: DriveResult) -> list[Any]:
    return [request for request in result.requests if request.path != "/token"]


class TestPagedLists:
    def test_orders_ask_for_every_status_and_method_until_an_empty_page(self) -> None:
        result = _run(
            "orders",
            "/orders",
            [
                ScriptedResponse(json={"orders": [{"orderId": "A1"}]}),
                ScriptedResponse(json={"orders": [{"orderId": "A2"}]}),
                EMPTY,
            ],
        )

        assert result.raised is None
        token_request = result.requests[0]
        assert token_request.path == "/token"
        assert token_request.headers["authorization"] == "Basic Ym9sX2lkOmJvbF9zZWNyZXQ="
        assert token_request.body == b"grant_type=client_credentials"
        api = _api(result)
        assert [request.param("page") for request in api] == ["1", "2", "3"]
        assert {(request.param("status"), request.param("fulfilment-method")) for request in api} == {("ALL", "ALL")}
        assert api[0].headers["accept"] == "application/vnd.retailer.v10+json"
        assert api[0].headers["authorization"] == "Bearer tok"
        assert [row["orderId"] for row in result.rows] == ["A1", "A2"]
        assert result.saved_states == [BolRetailerResumeConfig(page=2), BolRetailerResumeConfig(page=3)]

    def test_shipments_walk_one_pass_per_fulfilment_method(self) -> None:
        result = _run(
            "shipments",
            "/shipments",
            [
                ScriptedResponse(json={"shipments": [{"shipmentId": "1"}]}),
                EMPTY,
                ScriptedResponse(json={"shipments": [{"shipmentId": "2"}]}),
                EMPTY,
            ],
        )

        assert result.raised is None
        assert [(r.param("fulfilment-method"), r.param("page")) for r in _api(result)] == [
            ("FBR", "1"),
            ("FBR", "2"),
            ("FBB", "1"),
            ("FBB", "2"),
        ]
        assert [row["shipmentId"] for row in result.rows] == ["1", "2"]
        # The empty page that ends the first pass stages the second pass, and the safe point commits it.
        assert BolRetailerResumeConfig(pass_index=1) in result.committed_states

    def test_returns_resume_at_the_saved_pass_and_page(self) -> None:
        result = _run(
            "returns",
            "/returns",
            [EMPTY, EMPTY],
            resume_state=BolRetailerResumeConfig(pass_index=2, page=3),
        )

        assert result.raised is None
        assert [(r.param("handled"), r.param("fulfilment-method"), r.param("page")) for r in _api(result)] == [
            ("false", "FBB", "3"),
            ("true", "FBB", "1"),
        ]


class TestInvoices:
    @time_machine.travel(datetime(2026, 10, 15, 12, tzinfo=UTC), tick=False)
    def test_requests_31_day_windows_up_to_today(self) -> None:
        result = _run(
            "invoices",
            "/invoices",
            [ScriptedResponse(json={"invoiceListItems": [{"invoiceId": "INV-1"}]}), ScriptedResponse(json={})],
            resume_state=BolRetailerResumeConfig(window_start="2026-09-05"),
        )

        assert result.raised is None
        assert [(r.param("period-start-date"), r.param("period-end-date")) for r in _api(result)] == [
            ("2026-09-05", "2026-10-05"),
            ("2026-10-06", "2026-10-15"),
        ]
        assert [row["invoiceId"] for row in result.rows] == ["INV-1"]
        assert result.saved_states == [BolRetailerResumeConfig(window_start="2026-10-06")]


class TestOffers:
    @pytest.mark.parametrize(
        ("inputs", "expected_since"),
        [
            ({}, None),
            (
                {
                    "incremental_field": "lastModifiedDateTime",
                    "db_incremental_field_last_value": datetime(2026, 10, 1, 8, 30, tzinfo=UTC),
                },
                "2026-10-01T08:30:00Z",
            ),
        ],
    )
    def test_walks_the_cursor_on_v11_and_filters_on_the_watermark(
        self, inputs: dict[str, Any], expected_since: str | None
    ) -> None:
        result = _run(
            "offers",
            "/offers",
            [
                ScriptedResponse(json={"offers": [{"offerId": "o1"}], "page": {"pageSize": 100, "nextCursor": "c2"}}),
                ScriptedResponse(json={"offers": [{"offerId": "o2"}], "page": {"pageSize": 100, "nextCursor": None}}),
            ],
            **inputs,
        )

        assert result.raised is None
        api = _api(result)
        assert [r.param("cursor") for r in api] == [None, "c2"]
        assert {r.param("last-modified-date-time") for r in api} == {expected_since}
        assert api[0].headers["accept"] == "application/vnd.retailer.v11+json"
        assert result.saved_states == [BolRetailerResumeConfig(cursor="c2", modified_since=expected_since)]

    def test_resume_keeps_the_cursor_and_the_interrupted_filter(self) -> None:
        result = _run(
            "offers",
            "/offers",
            [ScriptedResponse(json={"offers": [], "page": {"nextCursor": None}})],
            resume_state=BolRetailerResumeConfig(cursor="c9", modified_since="2026-09-01T00:00:00Z"),
            incremental_field="lastModifiedDateTime",
            db_incremental_field_last_value=datetime(2026, 10, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [(r.param("cursor"), r.param("last-modified-date-time")) for r in _api(result)] == [
            ("c9", "2026-09-01T00:00:00Z")
        ]


class TestTokenErrors:
    def test_rejected_client_credentials_fail_with_the_permanent_marker(self) -> None:
        config = BolRetailerSourceConfig(client_id="bol_id", client_secret="wrong")
        result = SourceDriver(BolRetailerSource(), config).run(
            "inventory", always(ScriptedResponse(status=401, json={"error": "invalid_client"}))
        )

        assert result.raised is not None
        assert OAUTH2_PERMANENT_ERROR_MARKER in str(result.raised)
        assert "invalid_client" in str(result.raised)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("response", "expected_valid", "message_fragment"),
        [
            (TOKEN, True, None),
            (ScriptedResponse(status=401, json={"error": "invalid_client"}), False, "rejected the client ID"),
            (ScriptedResponse(status=500, json={}), False, "Could not connect"),
            (ConnectionError("boom"), False, "Could not connect"),
        ],
    )
    def test_maps_the_token_probe(self, response: Any, expected_valid: bool, message_fragment: str | None) -> None:
        with scripted_network(always(response)) as network:
            is_valid, message = validate_credentials("bol_id", "bol_secret")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message
        assert {request.path for request in network.requests_log} == {"/token"}
