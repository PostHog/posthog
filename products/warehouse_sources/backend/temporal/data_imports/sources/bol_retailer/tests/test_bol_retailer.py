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
    @time_machine.travel(datetime(2026, 10, 15, 12, tzinfo=UTC), tick=False)
    def test_order_items_read_one_change_day_at_a_time_from_the_watermark(self) -> None:
        # The plain list drops handled orders after 48 hours, so history comes from `latest-change-date`.
        order = {
            "orderId": "A1",
            "orderPlacedDateTime": "2026-10-14T09:00:00+02:00",
            "orderItems": [
                {"orderItemId": "1", "latestChangedDateTime": "2026-10-14T23:30:00+02:00"},
                {"orderItemId": "2", "latestChangedDateTime": "2026-10-14T22:00:00+00:00"},
            ],
        }
        result = _run(
            "order_items",
            "/orders",
            [ScriptedResponse(json={"orders": [order]}), EMPTY, EMPTY],
            incremental_field="latestChangedDateTime",
            db_incremental_field_last_value=datetime(2026, 10, 14, 8, tzinfo=UTC),
        )

        assert result.raised is None
        token_request = result.requests[0]
        assert token_request.path == "/token"
        assert token_request.headers["authorization"] == "Basic Ym9sX2lkOmJvbF9zZWNyZXQ="
        assert token_request.body == b"grant_type=client_credentials"
        api = _api(result)
        assert [(r.param("latest-change-date"), r.param("page")) for r in api] == [
            ("2026-10-14", "1"),
            ("2026-10-14", "2"),
            ("2026-10-15", "1"),
        ]
        assert {(r.param("status"), r.param("fulfilment-method")) for r in api} == {("ALL", "ALL")}
        assert api[0].headers["accept"] == "application/vnd.retailer.v10+json"
        assert api[0].headers["authorization"] == "Bearer tok"
        # A day's response holds only the items changed that day, so each item is its own row.
        assert [(row["orderId"], row["orderItemId"], row["orderPlacedDateTime"]) for row in result.rows] == [
            ("A1", "1", "2026-10-14T09:00:00+02:00"),
            ("A1", "2", "2026-10-14T09:00:00+02:00"),
        ]
        assert result.saved_states == [
            BolRetailerResumeConfig(pass_index=0, page=2, window_start="2026-10-14"),
            BolRetailerResumeConfig(pass_index=1, window_start="2026-10-14"),
        ]

    @time_machine.travel(datetime(2026, 10, 15, 12, tzinfo=UTC), tick=False)
    def test_resumed_order_items_rebuild_the_days_from_the_saved_window_start(self) -> None:
        # The watermark moved past the saved window start, which must not shift the saved pass index.
        result = _run(
            "order_items",
            "/orders",
            [EMPTY, EMPTY],
            resume_state=BolRetailerResumeConfig(pass_index=1, page=2, window_start="2026-10-13"),
            incremental_field="latestChangedDateTime",
            db_incremental_field_last_value=datetime(2026, 10, 14, 8, tzinfo=UTC),
        )

        assert result.raised is None
        assert [(r.param("latest-change-date"), r.param("page")) for r in _api(result)] == [
            ("2026-10-14", "2"),
            ("2026-10-15", "1"),
        ]

    @time_machine.travel(datetime(2026, 10, 15, 12, tzinfo=UTC), tick=False)
    def test_a_first_order_items_sync_reaches_three_months_back(self) -> None:
        result = _run("order_items", "/orders", [EMPTY] * 91)

        assert result.raised is None
        days = [r.param("latest-change-date") for r in _api(result)]
        assert (days[0], days[-1], len(days)) == ("2026-07-17", "2026-10-15", 91)

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

    def test_incremental_shipments_stop_each_pass_at_the_first_page_older_than_the_watermark(self) -> None:
        # The list returns newest shipments first and reaches three months back.
        def shipment(shipment_id: str, day: int) -> dict[str, Any]:
            return {"shipmentId": shipment_id, "shipmentDateTime": f"2026-10-{day:02d}T12:00:00+02:00"}

        result = _run(
            "shipments",
            "/shipments",
            [
                ScriptedResponse(json={"shipments": [shipment("4", 14), shipment("3", 9)]}),
                ScriptedResponse(json={"shipments": [shipment("2", 8), shipment("1", 2)]}),
                ScriptedResponse(json={"shipments": [shipment("5", 1)]}),
            ],
            incremental_field="shipmentDateTime",
            db_incremental_field_last_value=datetime(2026, 10, 10, tzinfo=UTC),
        )

        assert result.raised is None
        assert [(r.param("fulfilment-method"), r.param("page")) for r in _api(result)] == [
            ("FBR", "1"),
            ("FBR", "2"),
            ("FBB", "1"),
        ]
        assert [row["shipmentId"] for row in result.rows] == ["4", "3", "2", "1", "5"]
        # The stop stages the next pass, so a resume does not go back to the stopped pass's next page.
        assert result.saved_states == [
            BolRetailerResumeConfig(page=2),
            BolRetailerResumeConfig(page=3),
            BolRetailerResumeConfig(pass_index=1),
            BolRetailerResumeConfig(pass_index=1, page=2),
        ]

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
