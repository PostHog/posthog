from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import pytest
import time_machine

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.amazon_selling_partner import (
    ACCESS_DENIED_MESSAGE,
    LWA_REJECTED_MESSAGE,
    UNAVAILABLE_MESSAGE,
    AmazonSellingPartnerResumeConfig,
    to_iso8601,
    transaction_windows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.settings import (
    EARLIEST_START,
    ORDERS_INCLUDED_DATA,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.source import (
    AmazonSellingPartnerSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazonsellingpartner import (
    AmazonSellingPartnerSourceConfig,
)

TOKEN_PATH = "/auth/o2/token"
ORDERS_PATH = "/orders/2026-01-01/orders"
TRANSACTIONS_PATH = "/finances/2024-06-19/transactions"
SUMMARIES_PATH = "/fba/inventory/v1/summaries"
PARTICIPATIONS_PATH = "/sellers/v1/marketplaceParticipations"

TOKEN = ScriptedResponse(
    json={"access_token": "Atza|access", "refresh_token": "Atzr|refresh", "token_type": "bearer", "expires_in": 3600}
)
LWA_INVALID_GRANT = ScriptedResponse(
    status=400,
    json={"error": "invalid_grant", "error_description": "The request has an invalid grant parameter : refresh_token"},
)
SP_API_FORBIDDEN = ScriptedResponse(
    status=403,
    json={"errors": [{"code": "Unauthorized", "message": "Access to requested resource is denied.", "details": ""}]},
)
NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)


def _driver(marketplace_ids: str | None = None) -> SourceDriver:
    config = AmazonSellingPartnerSourceConfig(
        client_id="amzn1.application-oa2-client.test",
        client_secret="client-secret",
        refresh_token="Atzr|refresh",
        region="na",
        marketplace_ids=marketplace_ids,
    )
    return SourceDriver(AmazonSellingPartnerSource(), config)


def _api_requests(result: DriveResult) -> list[RecordedRequest]:
    return [request for request in result.requests if request.path != TOKEN_PATH]


def _order(order_id: str, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "orderId": order_id,
        "createdTime": "2026-01-02T03:04:05Z",
        "lastUpdatedTime": "2026-01-03T00:00:00Z",
        "salesChannel": {"marketplaceId": "ATVPDKIKX0DER", "marketplaceName": "Amazon.com"},
        "orderItems": items or [],
    }


def _orders_page(orders: list[dict[str, Any]], next_token: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"orders": orders, "pagination": {"nextToken": next_token} if next_token else {}})


def _transactions_page(ids: list[str], next_token: str | None = None) -> ScriptedResponse:
    payload: dict[str, Any] = {
        "transactions": [{"transactionId": id, "postedDate": "2026-09-02T00:00:00Z"} for id in ids]
    }
    if next_token:
        payload["nextToken"] = next_token
    return ScriptedResponse(json={"payload": payload})


def _summaries_page(skus: list[str], next_token: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"payload": {"inventorySummaries": [{"sellerSku": sku, "totalQuantity": 1} for sku in skus]}}
    if next_token:
        body["pagination"] = {"nextToken": next_token}
    return ScriptedResponse(json=body)


class TestOrders:
    def test_walks_pages_with_the_lwa_token(self) -> None:
        result = _driver("ATVPDKIKX0DER").run(
            "orders",
            route(
                {
                    TOKEN_PATH: [TOKEN],
                    ORDERS_PATH: [_orders_page([_order("1"), _order("2")], "tok2"), _orders_page([_order("3")])],
                }
            ),
        )

        assert result.raised is None
        token_request = result.requests[0]
        assert token_request.path == TOKEN_PATH
        assert parse_qs((token_request.body or b"").decode()) == {
            "grant_type": ["refresh_token"],
            "refresh_token": ["Atzr|refresh"],
            "client_id": ["amzn1.application-oa2-client.test"],
            "client_secret": ["client-secret"],
        }
        api_requests = _api_requests(result)
        assert [request.path for request in api_requests] == [ORDERS_PATH, ORDERS_PATH]
        assert all(request.headers["x-amz-access-token"] == "Atza|access" for request in api_requests)
        assert [request.param("paginationToken") for request in api_requests] == [None, "tok2"]
        assert api_requests[0].param("maxResultsPerPage") == "100"
        assert api_requests[0].param("includedData") == ORDERS_INCLUDED_DATA
        assert [row["orderId"] for row in result.rows] == ["1", "2", "3"]
        assert result.saved_states == [AmazonSellingPartnerResumeConfig(next_token="tok2")]

    @pytest.mark.parametrize(
        ("incremental_field", "last_value", "marketplace_ids", "expected_after", "expected_marketplaces"),
        [
            (None, None, None, EARLIEST_START, None),
            (
                "lastUpdatedTime",
                datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC),
                "ATVPDKIKX0DER, A1F83G8C2ARO7P",
                "2026-03-04T05:06:07Z",
                "ATVPDKIKX0DER,A1F83G8C2ARO7P",
            ),
            ("lastUpdatedTime", "2026-03-04 05:06:07", None, "2026-03-04T05:06:07Z", None),
        ],
    )
    def test_request_shaping(
        self,
        incremental_field: str | None,
        last_value: Any,
        marketplace_ids: str | None,
        expected_after: str,
        expected_marketplaces: str | None,
    ) -> None:
        result = _driver(marketplace_ids).run(
            "orders",
            route({TOKEN_PATH: [TOKEN], ORDERS_PATH: [_orders_page([_order("1")])]}),
            incremental_field=incremental_field,
            db_incremental_field_last_value=last_value,
        )

        request = _api_requests(result)[0]
        assert request.param("lastUpdatedAfter") == expected_after
        assert request.param("marketplaceIds") == expected_marketplaces
        assert request.param("createdAfter") is None

    def test_order_items_explode_each_order_with_its_parent_fields(self) -> None:
        items = [{"orderItemId": "i1", "quantityOrdered": 2}, {"orderItemId": "i2", "quantityOrdered": 1}]
        result = _driver().run(
            "order_items",
            route({TOKEN_PATH: [TOKEN], ORDERS_PATH: [_orders_page([_order("A", items), _order("B")])]}),
        )

        assert result.raised is None
        assert result.rows == [
            {
                "orderId": "A",
                "createdTime": "2026-01-02T03:04:05Z",
                "lastUpdatedTime": "2026-01-03T00:00:00Z",
                "marketplaceId": "ATVPDKIKX0DER",
                "orderItemId": "i1",
                "quantityOrdered": 2,
            },
            {
                "orderId": "A",
                "createdTime": "2026-01-02T03:04:05Z",
                "lastUpdatedTime": "2026-01-03T00:00:00Z",
                "marketplaceId": "ATVPDKIKX0DER",
                "orderItemId": "i2",
                "quantityOrdered": 1,
            },
        ]

    def test_resumes_from_the_saved_page_token(self) -> None:
        result = _driver().run(
            "orders",
            route({TOKEN_PATH: [TOKEN], ORDERS_PATH: [_orders_page([_order("9")])]}),
            resume_state=AmazonSellingPartnerResumeConfig(next_token="tok9"),
        )

        assert _api_requests(result)[0].param("paginationToken") == "tok9"
        assert [row["orderId"] for row in result.rows] == ["9"]


class TestTransactions:
    @pytest.fixture(autouse=True)
    def frozen_clock(self) -> Iterator[None]:
        with time_machine.travel(NOW, tick=False):
            yield

    def test_full_refresh_walks_contiguous_windows_from_the_earliest_start(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == TOKEN_PATH:
                return TOKEN
            return _transactions_page([request.param("postedAfter") or ""])

        result = _driver().run("transactions", respond)

        assert result.raised is None
        windows = transaction_windows(datetime(2016, 1, 1, tzinfo=UTC), NOW)
        api_requests = _api_requests(result)
        assert [request.param("postedAfter") for request in api_requests] == [
            to_iso8601(window.posted_after) for window in windows
        ]
        assert [request.param("postedBefore") for request in api_requests] == [
            to_iso8601(window.posted_before) for window in windows
        ]
        assert api_requests[0].param("postedAfter") == EARLIEST_START
        assert api_requests[-1].param("postedBefore") == "2026-10-15T11:57:00Z"
        assert all(request.param("nextToken") is None for request in api_requests)
        assert result.saved_states == [
            AmazonSellingPartnerResumeConfig(window_start=to_iso8601(window.posted_after)) for window in windows[1:]
        ]
        assert len(result.rows) == len(windows)

    def test_incremental_starts_at_the_watermark_and_stages_the_page_token_before_its_page(self) -> None:
        result = _driver().run(
            "transactions",
            route(
                {
                    TOKEN_PATH: [TOKEN],
                    TRANSACTIONS_PATH: [_transactions_page(["t1"], "n2"), _transactions_page(["t2"])],
                }
            ),
            incremental_field="postedDate",
            db_incremental_field_last_value=datetime(2026, 9, 1, tzinfo=UTC),
        )

        assert result.raised is None
        api_requests = _api_requests(result)
        assert [request.param("postedAfter") for request in api_requests] == ["2026-09-01T00:00:00Z"] * 2
        assert [request.param("postedBefore") for request in api_requests] == ["2026-10-15T11:57:00Z"] * 2
        assert [request.param("nextToken") for request in api_requests] == [None, "n2"]
        expected = AmazonSellingPartnerResumeConfig(window_start="2026-09-01T00:00:00Z", next_token="n2")
        assert result.saved_states == [expected]
        assert result.committed_states == [expected]

    def test_resumes_from_the_saved_window_and_token(self) -> None:
        result = _driver().run(
            "transactions",
            route({TOKEN_PATH: [TOKEN], TRANSACTIONS_PATH: [_transactions_page(["t3"])]}),
            resume_state=AmazonSellingPartnerResumeConfig(window_start="2026-09-01T00:00:00Z", next_token="n2"),
        )

        request = _api_requests(result)[0]
        assert request.param("postedAfter") == "2026-09-01T00:00:00Z"
        assert request.param("nextToken") == "n2"

    def test_a_watermark_inside_the_request_margin_makes_no_request(self) -> None:
        result = _driver().run(
            "transactions",
            [],
            incremental_field="postedDate",
            db_incremental_field_last_value=NOW - timedelta(seconds=60),
        )

        assert result.raised is None
        assert result.requests == []
        assert result.rows == []


class TestInventorySummaries:
    def test_discovers_marketplaces_and_tags_each_row(self) -> None:
        participations = ScriptedResponse(
            json={
                "payload": [
                    {"marketplace": {"id": "A"}, "participation": {"isParticipating": True}},
                    {"marketplace": {"id": "X"}, "participation": {"isParticipating": False}},
                    {"marketplace": {"id": "B"}, "participation": {"isParticipating": True}},
                ]
            }
        )
        result = _driver().run(
            "inventory_summaries",
            route(
                {
                    TOKEN_PATH: [TOKEN],
                    PARTICIPATIONS_PATH: [participations],
                    SUMMARIES_PATH: [
                        _summaries_page(["sku1"], "next"),
                        _summaries_page(["sku2"]),
                        _summaries_page(["sku3"]),
                    ],
                }
            ),
        )

        assert result.raised is None
        api_requests = _api_requests(result)
        assert [request.path for request in api_requests] == [PARTICIPATIONS_PATH] + [SUMMARIES_PATH] * 3
        summaries = api_requests[1:]
        assert [request.param("granularityId") for request in summaries] == ["A", "A", "B"]
        assert [request.param("marketplaceIds") for request in summaries] == ["A", "A", "B"]
        assert [request.param("nextToken") for request in summaries] == [None, "next", None]
        assert summaries[0].param("granularityType") == "Marketplace"
        assert summaries[0].param("details") == "true"
        assert summaries[0].param("startDateTime") is None
        assert [(row["marketplaceId"], row["sellerSku"]) for row in result.rows] == [
            ("A", "sku1"),
            ("A", "sku2"),
            ("B", "sku3"),
        ]
        assert result.saved_states == [
            AmazonSellingPartnerResumeConfig(completed_marketplaces=["A"]),
            AmazonSellingPartnerResumeConfig(completed_marketplaces=["A", "B"]),
        ]

    @pytest.mark.parametrize(
        ("watermark", "expected_start"),
        [
            ("2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00Z"),
            # Amazon rejects a start more than 18 months back, so an old watermark is clamped.
            ("2020-01-01T00:00:00+00:00", "2025-04-23T12:00:00Z"),
        ],
    )
    def test_resume_skips_finished_marketplaces_and_incremental_sends_the_start_date(
        self, watermark: str, expected_start: str
    ) -> None:
        with time_machine.travel(NOW, tick=False):
            result = _driver("A,B").run(
                "inventory_summaries",
                route({TOKEN_PATH: [TOKEN], SUMMARIES_PATH: [_summaries_page(["sku9"])]}),
                resume_state=AmazonSellingPartnerResumeConfig(completed_marketplaces=["A"]),
                incremental_field="lastUpdatedTime",
                db_incremental_field_last_value=watermark,
            )

        assert result.raised is None
        api_requests = _api_requests(result)
        assert [request.path for request in api_requests] == [SUMMARIES_PATH]
        assert api_requests[0].param("granularityId") == "B"
        assert api_requests[0].param("startDateTime") == expected_start


class TestErrors:
    def test_a_rejected_refresh_token_is_a_permanent_auth_error(self) -> None:
        result = _driver().run("orders", always(LWA_INVALID_GRANT))

        assert isinstance(result.raised, OAuth2AuthRequestError)
        assert result.raised.is_permanent
        assert "invalid_grant" in str(result.raised)
        assert result.rows == []

    def test_a_forbidden_api_response_keeps_the_vendor_error_code(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            return TOKEN if request.path == TOKEN_PATH else SP_API_FORBIDDEN

        result = _driver().run("orders", respond)

        assert isinstance(result.raised, requests.HTTPError)
        message = str(result.raised)
        assert (
            "403 Client Error: Forbidden for url: https://sellingpartnerapi-na.amazon.com/orders/2026-01-01/orders"
            in message
        )
        assert message.endswith("| api error: code=Unauthorized")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("token_answer", "probe_answer", "expected"),
        [
            (LWA_INVALID_GRANT, None, (False, LWA_REJECTED_MESSAGE)),
            (ScriptedResponse(status=503, json={}), None, (False, UNAVAILABLE_MESSAGE)),
            (TOKEN, ScriptedResponse(json={"payload": []}), (True, None)),
            (TOKEN, SP_API_FORBIDDEN, (False, ACCESS_DENIED_MESSAGE)),
        ],
    )
    def test_maps_the_vendor_answers(
        self, token_answer: ScriptedResponse, probe_answer: ScriptedResponse | None, expected: tuple[bool, str | None]
    ) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == TOKEN_PATH:
                return token_answer
            assert probe_answer is not None
            return probe_answer

        with scripted_network(respond) as network:
            assert validate_credentials("na", "client", "secret", "Atzr|refresh") == expected
        assert network.requests_log[-1].path == (TOKEN_PATH if probe_answer is None else PARTICIPATIONS_PATH)

    def test_a_network_failure_is_reported_as_unavailable(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))):
            assert validate_credentials("na", "client", "secret", "Atzr|refresh") == (False, UNAVAILABLE_MESSAGE)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
        ("2026-01-02T03:04:05+02:00", "2026-01-02T01:04:05Z"),
        ("2026-01-02", "2026-01-02T00:00:00Z"),
        ("not-a-date", "not-a-date"),
    ],
)
def test_to_iso8601(value: Any, expected: str) -> None:
    assert to_iso8601(value) == expected


def test_transaction_windows_are_contiguous_and_end_before_the_request_margin() -> None:
    start = NOW - timedelta(days=400)

    windows = transaction_windows(start, NOW)

    assert [window.posted_before - window.posted_after for window in windows[:-1]] == [timedelta(days=179)] * 2
    assert [window.posted_before for window in windows[:-1]] == [window.posted_after for window in windows[1:]]
    assert windows[0].posted_after == start
    assert windows[-1].posted_before == NOW - timedelta(seconds=180)
    assert transaction_windows(NOW - timedelta(seconds=60), NOW) == []
