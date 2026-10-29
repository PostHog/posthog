import gzip
import json
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import pytest
import time_machine

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.amazon_selling_partner import (
    ACCESS_DENIED_MESSAGE,
    LWA_REJECTED_MESSAGE,
    MISSING_MARKETPLACES_MESSAGE,
    SELLER_ONLY_MESSAGE,
    UNAVAILABLE_MESSAGE,
    VENDOR_ONLY_MESSAGE,
    AmazonSellingPartnerResumeConfig,
    VendorReportError,
    parse_marketplace_ids,
    probe_endpoint_permissions,
    report_windows,
    to_iso8601,
    transaction_windows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.settings import (
    EARLIEST_START,
    ORDERS_INCLUDED_DATA,
    REPORT_DOCUMENTS_PATH as DOCUMENTS_PATH,
    REPORTS_PATH,
    VENDOR_REPORTS,
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
        # Order bodies carry buyer data, so no session may store HTTP samples of them.
        assert result.session_options and all(options.get("capture") is False for options in result.session_options)

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

    def test_buyer_personal_data_is_dropped_from_orders_and_items(self) -> None:
        item = {
            "orderItemId": "i1",
            "product": {"asin": "B01", "customization": {"customizedUrl": "https://example.com/c"}},
            "fulfillment": {"packing": {"giftOption": {"giftMessage": "Happy birthday", "giftWrapLevel": "CLASSIC"}}},
        }
        order = {**_order("A", [item]), "tax": {"taxRegistrations": [{"legalName": "Jane Example"}], "taxRate": 0.2}}

        for endpoint in ("orders", "order_items"):
            result = _driver().run(
                endpoint, route({TOKEN_PATH: [TOKEN], ORDERS_PATH: [_orders_page([json.loads(json.dumps(order))])]})
            )

            assert result.raised is None
            serialized = json.dumps(result.rows)
            assert "Jane Example" not in serialized
            assert "Happy birthday" not in serialized
            assert "customizedUrl" not in serialized
            assert "CLASSIC" in serialized

    def test_orders_keep_retrying_through_amazons_refill_interval(self) -> None:
        throttled = ScriptedResponse(status=429, json={"errors": [{"code": "QuotaExceeded"}]})
        result = _driver().run(
            "orders",
            route({TOKEN_PATH: [TOKEN], ORDERS_PATH: [throttled] * 8 + [_orders_page([_order("1")])]}),
        )

        assert result.raised is None
        assert [row["orderId"] for row in result.rows] == ["1"]

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
        assert [(r.param("postedAfter"), r.param("postedBefore")) for r in api_requests] == [
            (to_iso8601(w.posted_after), to_iso8601(w.posted_before)) for w in windows
        ]
        assert api_requests[0].param("postedAfter") == EARLIEST_START
        assert api_requests[-1].param("postedBefore") == "2026-10-15T11:57:00Z"
        assert all(r.param("nextToken") is None and r.param("transactionStatus") is None for r in api_requests)
        assert result.saved_states == [
            AmazonSellingPartnerResumeConfig(
                window_start=to_iso8601(w.posted_after), window_end=to_iso8601(w.posted_before)
            )
            for w in windows[1:]
        ]
        assert len(result.rows) == len(windows)

    def test_incremental_walks_from_the_watermark_then_sweeps_released_deferred_transactions(self) -> None:
        result = _driver().run(
            "transactions",
            route(
                {
                    TOKEN_PATH: [TOKEN],
                    TRANSACTIONS_PATH: [
                        _transactions_page(["t1"], "n2"),
                        _transactions_page(["t2"]),
                        _transactions_page(["t-released"]),
                    ],
                }
            ),
            incremental_field="postedDate",
            db_incremental_field_last_value=datetime(2026, 9, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [
            (r.param("postedAfter"), r.param("postedBefore"), r.param("transactionStatus"), r.param("nextToken"))
            for r in _api_requests(result)
        ] == [
            ("2026-09-01T00:00:00Z", "2026-10-15T11:57:00Z", None, None),
            ("2026-09-01T00:00:00Z", "2026-10-15T11:57:00Z", None, "n2"),
            ("2026-08-16T11:57:00Z", "2026-10-15T11:57:00Z", "DEFERRED_RELEASED", None),
        ]
        assert [row["transactionId"] for row in result.rows] == ["t1", "t2", "t-released"]
        first_page_state = AmazonSellingPartnerResumeConfig(
            window_start="2026-09-01T00:00:00Z", window_end="2026-10-15T11:57:00Z", next_token="n2"
        )
        assert result.committed_states[0] == first_page_state

    def test_a_first_incremental_sync_skips_the_deferred_sweep(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            return TOKEN if request.path == TOKEN_PATH else _transactions_page([])

        result = _driver().run("transactions", respond, incremental_field="postedDate")

        assert result.raised is None
        assert all(request.param("transactionStatus") is None for request in _api_requests(result))

    @pytest.mark.parametrize(
        ("saved_window", "expected"),
        [
            (
                ("2026-10-01T00:00:00Z", "2026-10-14T00:00:00Z", "DEFERRED_RELEASED"),
                [("2026-10-01T00:00:00Z", "2026-10-14T00:00:00Z", "DEFERRED_RELEASED", "n2")],
            ),
            (
                ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", None),
                [
                    ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", None, "n2"),
                    ("2026-10-01T00:00:00Z", "2026-10-15T11:57:00Z", None, None),
                    ("2026-08-16T11:57:00Z", "2026-10-15T11:57:00Z", "DEFERRED_RELEASED", None),
                ],
            ),
        ],
    )
    def test_resume_reuses_the_saved_window_with_its_token(
        self, saved_window: tuple[str, str, str | None], expected: list[tuple[str, str, str | None, str | None]]
    ) -> None:
        window_start, window_end, transaction_status = saved_window

        def respond(request: RecordedRequest) -> ScriptedResponse:
            return TOKEN if request.path == TOKEN_PATH else _transactions_page(["t"])

        result = _driver().run(
            "transactions",
            respond,
            resume_state=AmazonSellingPartnerResumeConfig(
                window_start=window_start,
                window_end=window_end,
                transaction_status=transaction_status,
                next_token="n2",
            ),
            incremental_field="postedDate",
            db_incremental_field_last_value=datetime(2026, 9, 1, tzinfo=UTC),
        )

        assert [
            (r.param("postedAfter"), r.param("postedBefore"), r.param("transactionStatus"), r.param("nextToken"))
            for r in _api_requests(result)
        ] == expected


class TestInventorySummaries:
    def test_discovers_marketplaces_reads_each_one_whole_and_tags_rows(self) -> None:
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
        summaries = [request for request in _api_requests(result) if request.path == SUMMARIES_PATH]
        assert [(r.param("granularityId"), r.param("marketplaceIds"), r.param("nextToken")) for r in summaries] == [
            ("A", "A", None),
            ("A", "A", "next"),
            ("B", "B", None),
        ]
        assert summaries[0].param("details") == "true"
        assert all(r.param("startDateTime") is None for r in summaries)
        # Both pages of a marketplace arrive in one batch, so no page token waits on the pipeline.
        assert [[(row["marketplaceId"], row["sellerSku"]) for row in item] for item in result.items] == [
            [("A", "sku1"), ("A", "sku2")],
            [("B", "sku3")],
        ]
        assert result.committed_states == [
            AmazonSellingPartnerResumeConfig(completed_marketplaces=["A"]),
            AmazonSellingPartnerResumeConfig(completed_marketplaces=["A", "B"]),
        ]

    def test_resume_skips_finished_marketplaces(self) -> None:
        result = _driver("A,B").run(
            "inventory_summaries",
            route({TOKEN_PATH: [TOKEN], SUMMARIES_PATH: [_summaries_page(["sku9"])]}),
            resume_state=AmazonSellingPartnerResumeConfig(completed_marketplaces=["A"]),
        )

        assert result.raised is None
        assert [request.param("granularityId") for request in _api_requests(result)] == ["B"]

    def test_a_discovered_marketplace_inventory_does_not_cover_is_skipped(self) -> None:
        participations = ScriptedResponse(
            json={
                "payload": [
                    {"marketplace": {"id": "X"}, "participation": {"isParticipating": True}},
                    {"marketplace": {"id": "A"}, "participation": {"isParticipating": True}},
                ]
            }
        )
        invalid_marketplace = ScriptedResponse(
            status=400, json={"errors": [{"code": "InvalidInput", "message": "Invalid granularityId"}]}
        )

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == TOKEN_PATH:
                return TOKEN
            if request.path == PARTICIPATIONS_PATH:
                return participations
            return invalid_marketplace if request.param("granularityId") == "X" else _summaries_page(["sku1"])

        result = _driver().run("inventory_summaries", respond)

        assert result.raised is None
        assert [(row["marketplaceId"], row["sellerSku"]) for row in result.rows] == [("A", "sku1")]
        assert result.final_state == AmazonSellingPartnerResumeConfig(completed_marketplaces=["X", "A"])

    def test_a_400_after_the_first_page_of_a_discovered_marketplace_fails_the_sync(self) -> None:
        participations = ScriptedResponse(
            json={"payload": [{"marketplace": {"id": "A"}, "participation": {"isParticipating": True}}]}
        )
        expired_token = ScriptedResponse(
            status=400, json={"errors": [{"code": "InvalidInput", "message": "The next token has expired"}]}
        )

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == TOKEN_PATH:
                return TOKEN
            if request.path == PARTICIPATIONS_PATH:
                return participations
            return expired_token if request.param("nextToken") else _summaries_page(["sku1"], "next")

        result = _driver().run("inventory_summaries", respond)

        assert isinstance(result.raised, requests.HTTPError)
        assert result.final_state is None

    def test_a_configured_marketplace_that_amazon_rejects_fails_the_sync(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            return TOKEN if request.path == TOKEN_PATH else ScriptedResponse(status=400, json={"errors": []})

        result = _driver("X").run("inventory_summaries", respond)

        assert isinstance(result.raised, requests.HTTPError)

    def test_resume_inside_a_marketplace_skips_rows_already_handed_on(self) -> None:
        result = _driver("A").run(
            "inventory_summaries",
            route(
                {
                    TOKEN_PATH: [TOKEN],
                    SUMMARIES_PATH: [_summaries_page(["sku1", "sku2"], "next"), _summaries_page(["sku3"])],
                }
            ),
            resume_state=AmazonSellingPartnerResumeConfig(marketplace_id="A", last_seller_sku="sku2"),
        )

        assert result.raised is None
        assert [row["sellerSku"] for row in result.rows] == ["sku3"]
        assert result.final_state == AmazonSellingPartnerResumeConfig(completed_marketplaces=["A"])


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
        ("token_answer", "sellers_answer", "reports_answer", "marketplace_ids", "expected"),
        [
            (LWA_INVALID_GRANT, None, None, ["A"], (False, LWA_REJECTED_MESSAGE)),
            (ScriptedResponse(status=503, json={}), None, None, ["A"], (False, UNAVAILABLE_MESSAGE)),
            (TOKEN, ScriptedResponse(json={"payload": []}), None, [], (True, None)),
            # Vendor accounts get 403 from the Sellers API, so the Reports API decides.
            (TOKEN, SP_API_FORBIDDEN, ScriptedResponse(json={"reports": []}), ["A"], (True, None)),
            (
                TOKEN,
                SP_API_FORBIDDEN,
                ScriptedResponse(json={"reports": []}),
                [],
                (False, MISSING_MARKETPLACES_MESSAGE),
            ),
            # Wrong region or an app with no roles: both APIs refuse, so creation fails.
            (TOKEN, SP_API_FORBIDDEN, SP_API_FORBIDDEN, ["A"], (False, ACCESS_DENIED_MESSAGE)),
            (
                TOKEN,
                ScriptedResponse(status=401, json={"errors": [{"code": "Unauthorized"}]}),
                None,
                ["A"],
                (False, ACCESS_DENIED_MESSAGE),
            ),
        ],
    )
    def test_maps_the_vendor_answers(
        self,
        token_answer: ScriptedResponse,
        sellers_answer: ScriptedResponse | None,
        reports_answer: ScriptedResponse | None,
        marketplace_ids: list[str],
        expected: tuple[bool, str | None],
    ) -> None:
        answers = {TOKEN_PATH: token_answer, PARTICIPATIONS_PATH: sellers_answer, REPORTS_PATH: reports_answer}

        def respond(request: RecordedRequest) -> ScriptedResponse:
            answer = answers[request.path]
            assert answer is not None, request.path
            return answer

        with scripted_network(respond):
            assert validate_credentials("na", "client", "secret", "Atzr|refresh", marketplace_ids) == expected

    def test_a_network_failure_is_reported_as_unavailable(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))):
            assert validate_credentials("na", "client", "secret", "Atzr|refresh", ["A"]) == (
                False,
                UNAVAILABLE_MESSAGE,
            )


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


DOCUMENT_URL = "https://tortuga-prod-na.s3-external-1.amazonaws.com/doc.json?X-Amz-Signature=0123456789abcdef"


def _gzip_json(body: dict[str, Any]) -> bytes:
    return gzip.compress(json.dumps(body).encode())


class _ReportsVendor:
    """A scripted Reports API: each created report runs through the given statuses, then serves its rows."""

    def __init__(self, statuses: list[str], documents: list[dict[str, Any]]) -> None:
        self.statuses = statuses
        self.documents = documents
        self.created: list[dict[str, Any]] = []
        self.polls: dict[str, int] = {}

    def __call__(self, request: RecordedRequest) -> ScriptedResponse:
        if request.path == TOKEN_PATH:
            return TOKEN
        if request.method == "POST" and request.path == REPORTS_PATH:
            self.created.append(request.json())
            return ScriptedResponse(status=202, json={"reportId": f"r{len(self.created)}"})
        if request.path.startswith(f"{REPORTS_PATH}/"):
            report_id = request.path.rsplit("/", 1)[1]
            poll = self.polls.get(report_id, 0)
            self.polls[report_id] = poll + 1
            status = self.statuses[min(poll, len(self.statuses) - 1)]
            body: dict[str, Any] = {"reportId": report_id, "processingStatus": status}
            if status in ("DONE", "FATAL"):
                body["reportDocumentId"] = f"doc-{report_id}"
            return ScriptedResponse(json=body)
        if request.path.startswith(f"{DOCUMENTS_PATH}/"):
            return ScriptedResponse(
                json={"reportDocumentId": "doc", "url": DOCUMENT_URL, "compressionAlgorithm": "GZIP"}
            )
        if request.path == "/doc.json":
            index = sum(1 for poll_count in self.polls.values() if poll_count) - 1
            return ScriptedResponse(body=_gzip_json(self.documents[min(index, len(self.documents) - 1)]))
        raise AssertionError(f"unexpected request {request.method} {request.url}")


class TestVendorReports:
    @pytest.fixture(autouse=True)
    def frozen_clock(self) -> Iterator[None]:
        with time_machine.travel(NOW, tick=False):
            yield

    def test_daily_report_walks_windows_from_the_watermark_and_tags_rows(self) -> None:
        vendor = _ReportsVendor(
            ["IN_QUEUE", "IN_PROGRESS", "DONE"],
            [
                {"salesByAsin": [{"asin": "B01", "startDate": "2026-09-28", "shippedUnits": 3}]},
                {"salesByAsin": [{"asin": "B02", "startDate": "2026-10-05", "shippedUnits": 1}]},
            ],
        )

        result = _driver("ATVPDKIKX0DER").run(
            "vendor_sales", vendor, incremental_field="startDate", db_incremental_field_last_value=date(2026, 9, 28)
        )

        assert result.raised is None
        assert vendor.created == [
            {
                "reportType": "GET_VENDOR_SALES_REPORT",
                "marketplaceIds": ["ATVPDKIKX0DER"],
                "reportOptions": {
                    "reportPeriod": "DAY",
                    "distributorView": "MANUFACTURING",
                    "sellingProgram": "RETAIL",
                },
                "dataStartTime": "2026-09-28T00:00:00Z",
                "dataEndTime": "2026-10-04T23:59:59Z",
            },
            {
                "reportType": "GET_VENDOR_SALES_REPORT",
                "marketplaceIds": ["ATVPDKIKX0DER"],
                "reportOptions": {
                    "reportPeriod": "DAY",
                    "distributorView": "MANUFACTURING",
                    "sellingProgram": "RETAIL",
                },
                "dataStartTime": "2026-10-05T00:00:00Z",
                "dataEndTime": "2026-10-11T23:59:59Z",
            },
        ]
        assert result.rows == [
            {"marketplaceId": "ATVPDKIKX0DER", "asin": "B01", "startDate": "2026-09-28", "shippedUnits": 3},
            {"marketplaceId": "ATVPDKIKX0DER", "asin": "B02", "startDate": "2026-10-05", "shippedUnits": 1},
        ]
        download = next(request for request in result.requests if request.path == "/doc.json")
        assert "x-amz-access-token" not in download.headers
        assert result.committed_states[:2] == [
            AmazonSellingPartnerResumeConfig(
                marketplace_id="ATVPDKIKX0DER",
                window_start="2026-09-28T00:00:00Z",
                window_end="2026-10-04T23:59:59Z",
                report_id="r1",
            ),
            AmazonSellingPartnerResumeConfig(marketplace_id="ATVPDKIKX0DER", window_start="2026-10-05T00:00:00Z"),
        ]
        assert result.final_state == AmazonSellingPartnerResumeConfig(completed_marketplaces=["ATVPDKIKX0DER"])

    def test_resume_polls_the_saved_report_instead_of_creating_one(self) -> None:
        vendor = _ReportsVendor(["DONE"], [{"inventoryByAsin": [{"asin": "B03", "startDate": "2026-10-05"}]}])

        result = _driver("ATVPDKIKX0DER").run(
            "vendor_inventory",
            vendor,
            resume_state=AmazonSellingPartnerResumeConfig(
                marketplace_id="ATVPDKIKX0DER", window_start="2026-10-05T00:00:00Z", report_id="r9"
            ),
        )

        assert result.raised is None
        assert vendor.created == []
        assert vendor.polls == {"r9": 1}
        assert [row["asin"] for row in result.rows] == ["B03"]

    def test_resume_skips_rows_of_the_report_already_handed_on(self) -> None:
        rows = [{"asin": f"B{index:05}", "startDate": "2026-10-01"} for index in range(4500)]
        vendor = _ReportsVendor(["DONE"], [{"forecastByAsin": rows}])

        result = _driver("ATVPDKIKX0DER").run(
            "vendor_forecasts",
            vendor,
            resume_state=AmazonSellingPartnerResumeConfig(
                marketplace_id="ATVPDKIKX0DER", report_id="r7", rows_done=2000
            ),
        )

        assert result.raised is None
        assert vendor.created == []
        assert [row["asin"] for row in result.rows] == [row["asin"] for row in rows[2000:]]
        assert result.saved_states[0] == AmazonSellingPartnerResumeConfig(
            marketplace_id="ATVPDKIKX0DER", report_id="r7", rows_done=4000
        )

    def test_resume_polls_a_saved_report_older_than_the_moving_lookback_floor(self) -> None:
        vendor = _ReportsVendor(["CANCELLED"], [])

        result = _driver("ATVPDKIKX0DER").run(
            "vendor_real_time_sales",
            vendor,
            resume_state=AmazonSellingPartnerResumeConfig(
                marketplace_id="ATVPDKIKX0DER", window_start="2026-09-16T11:00:00Z", report_id="r5"
            ),
        )

        assert result.raised is None
        assert "r5" in vendor.polls
        assert vendor.created[0]["dataStartTime"] == "2026-09-17T11:00:00Z"

    def test_resume_starts_the_next_window_where_the_saved_report_ended(self) -> None:
        vendor = _ReportsVendor(["CANCELLED"], [])

        result = _driver("ATVPDKIKX0DER").run(
            "vendor_real_time_sales",
            vendor,
            resume_state=AmazonSellingPartnerResumeConfig(
                marketplace_id="ATVPDKIKX0DER",
                window_start="2026-10-15T08:00:00Z",
                window_end="2026-10-15T09:00:00Z",
                report_id="r6",
            ),
        )

        assert result.raised is None
        assert "r6" in vendor.polls
        assert [(body["dataStartTime"], body["dataEndTime"]) for body in vendor.created] == [
            ("2026-10-15T09:00:00Z", "2026-10-15T11:00:00Z")
        ]

    def test_forecasts_request_one_report_per_marketplace_without_a_date_range(self) -> None:
        vendor = _ReportsVendor(["CANCELLED"], [])

        result = _driver("ATVPDKIKX0DER,A2EUQ1WTGCTBG2").run("vendor_forecasts", vendor)

        assert result.raised is None
        assert vendor.created == [
            {
                "reportType": "GET_VENDOR_FORECASTING_REPORT",
                "marketplaceIds": [marketplace],
                "reportOptions": {"sellingProgram": "RETAIL"},
            }
            for marketplace in ("ATVPDKIKX0DER", "A2EUQ1WTGCTBG2")
        ]
        assert result.rows == []
        assert result.final_state == AmazonSellingPartnerResumeConfig(
            completed_marketplaces=["ATVPDKIKX0DER", "A2EUQ1WTGCTBG2"]
        )

    def test_real_time_sales_sends_the_marketplace_currency(self) -> None:
        vendor = _ReportsVendor(["CANCELLED"], [])

        result = _driver("A1F83G8C2ARO7P").run(
            "vendor_real_time_sales",
            vendor,
            incremental_field="startTime",
            db_incremental_field_last_value=datetime(2026, 10, 14, 9, 30, tzinfo=UTC),
        )

        assert result.raised is None
        assert vendor.created == [
            {
                "reportType": "GET_VENDOR_REAL_TIME_SALES_REPORT",
                "marketplaceIds": ["A1F83G8C2ARO7P"],
                "reportOptions": {"currencyCode": "GBP"},
                "dataStartTime": start,
                "dataEndTime": end,
            }
            for start, end in [
                ("2026-10-14T09:00:00Z", "2026-10-15T09:00:00Z"),
                ("2026-10-15T09:00:00Z", "2026-10-15T11:00:00Z"),
            ]
        ]

    def test_a_fatal_report_raises_with_amazons_error_details(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/doc.json":
                return ScriptedResponse(body=_gzip_json({"errorDetails": "Report date range is not available yet."}))
            return vendor(request)

        vendor = _ReportsVendor(["FATAL"], [])

        result = _driver("ATVPDKIKX0DER").run("vendor_forecasts", respond)

        assert isinstance(result.raised, VendorReportError)
        assert str(result.raised) == (
            "Amazon could not generate the GET_VENDOR_FORECASTING_REPORT report: Report date range is not available yet."
        )
        # The failed report is dropped, so the retry creates a new one instead of polling it again.
        assert result.final_state == AmazonSellingPartnerResumeConfig(marketplace_id="ATVPDKIKX0DER")

    def test_a_failed_download_keeps_the_presigned_url_out_of_the_error(self) -> None:
        vendor = _ReportsVendor(["DONE"], [])

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/doc.json":
                return ScriptedResponse(status=403, body=b"<Error><Code>AccessDenied</Code></Error>")
            return vendor(request)

        result = _driver("ATVPDKIKX0DER").run("vendor_forecasts", respond)

        assert isinstance(result.raised, requests.HTTPError)
        assert str(result.raised) == "Amazon report document download returned status=403"

    def test_create_report_waits_out_a_rate_limit(self) -> None:
        vendor = _ReportsVendor(["CANCELLED"], [])
        throttled = [ScriptedResponse(status=429, json={"errors": [{"code": "QuotaExceeded"}]})]

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.method == "POST" and request.path == REPORTS_PATH and throttled:
                return throttled.pop()
            return vendor(request)

        result = _driver("ATVPDKIKX0DER").run("vendor_forecasts", respond)

        assert result.raised is None
        assert [request.method for request in result.requests if request.path == REPORTS_PATH] == ["POST", "POST"]

    @pytest.mark.parametrize(
        ("fatal_reports", "expected_starts", "expected_rows", "raises"),
        [
            (
                {"r1"},
                ["2026-09-21T00:00:00Z", "2026-09-21T00:00:00Z", "2026-09-28T00:00:00Z", "2026-10-05T00:00:00Z"],
                3,
                False,
            ),
            ({"r1", "r2", "r3"}, ["2026-09-21T00:00:00Z"] * 3, 0, True),
        ],
    )
    def test_a_fatal_old_window_is_retried_and_never_passed(
        self, fatal_reports: set[str], expected_starts: list[str], expected_rows: int, raises: bool
    ) -> None:
        vendor = _ReportsVendor(["DONE"], [{"salesByAsin": [{"asin": "B07", "startDate": "2026-10-05"}]}])

        def respond(request: RecordedRequest) -> ScriptedResponse:
            report_id = request.path.rsplit("/", 1)[1]
            if request.path.startswith(f"{REPORTS_PATH}/") and report_id in fatal_reports:
                return ScriptedResponse(json={"reportId": report_id, "processingStatus": "FATAL"})
            return vendor(request)

        result = _driver("ATVPDKIKX0DER").run(
            "vendor_sales", respond, incremental_field="startDate", db_incremental_field_last_value=date(2026, 9, 21)
        )

        assert [body["dataStartTime"] for body in vendor.created] == expected_starts
        assert [row["asin"] for row in result.rows] == ["B07"] * expected_rows
        if raises:
            assert isinstance(result.raised, VendorReportError)
            assert result.final_state == AmazonSellingPartnerResumeConfig(
                marketplace_id="ATVPDKIKX0DER", window_start="2026-09-21T00:00:00Z"
            )
        else:
            assert result.raised is None

    def test_a_document_url_outside_amazon_is_refused(self) -> None:
        vendor = _ReportsVendor(["DONE"], [])

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path.startswith(f"{DOCUMENTS_PATH}/"):
                return ScriptedResponse(json={"reportDocumentId": "doc", "url": "https://evil.example.com/doc.json"})
            return vendor(request)

        result = _driver("ATVPDKIKX0DER").run("vendor_forecasts", respond)

        assert isinstance(result.raised, ValueError)
        assert all(request.origin != "https://evil.example.com" for request in result.requests)

    def test_vendor_tables_need_marketplace_ids(self) -> None:
        result = _driver().run("vendor_sales", [])

        assert isinstance(result.raised, ValueError)
        assert str(result.raised) == MISSING_MARKETPLACES_MESSAGE
        assert result.requests == []


@pytest.mark.parametrize(
    ("endpoint", "start", "resumed", "expected"),
    [
        # A full refresh of a daily report starts at the oldest day Amazon keeps and stops four days back.
        ("vendor_sales", None, False, ("2022-10-17T00:00:00Z", "2022-10-23T23:59:59Z", 208, "2026-10-11T23:59:59Z")),
        # An hourly report stops at the last hour that closed five minutes before now.
        (
            "vendor_real_time_sales",
            None,
            False,
            ("2026-09-16T12:00:00Z", "2026-09-17T12:00:00Z", 29, "2026-10-15T11:00:00Z"),
        ),
        ("vendor_sales", datetime(2026, 10, 12, tzinfo=UTC), False, None),
        # A resumed report keeps its start after the lookback floor moved past it.
        (
            "vendor_real_time_sales",
            datetime(2026, 9, 16, 11, tzinfo=UTC),
            True,
            ("2026-09-16T11:00:00Z", "2026-09-17T11:00:00Z", 29, "2026-10-15T11:00:00Z"),
        ),
    ],
)
def test_report_windows(
    endpoint: str, start: datetime | None, resumed: bool, expected: tuple[str, str, int, str] | None
) -> None:
    windows = report_windows(VENDOR_REPORTS[endpoint], start, NOW, resumed=resumed)

    if expected is None:
        assert windows == []
        return
    first_start, first_end, count, last_end = expected
    assert (windows[0].data_start_time, windows[0].data_end_time, len(windows), windows[-1].data_end_time) == (
        first_start,
        first_end,
        count,
        last_end,
    )


PARTICIPATING_IN_A = ScriptedResponse(
    json={"payload": [{"marketplace": {"id": "A"}, "participation": {"isParticipating": True}}]}
)


@pytest.mark.parametrize(
    ("forbidden_paths", "marketplace_ids", "expected", "probed_paths"),
    [
        (
            {REPORTS_PATH},
            "A",
            {"orders": None, "inventory_summaries": None, "vendor_sales": VENDOR_ONLY_MESSAGE},
            [ORDERS_PATH, SUMMARIES_PATH, REPORTS_PATH],
        ),
        (
            {ORDERS_PATH, SUMMARIES_PATH},
            "A",
            {"orders": SELLER_ONLY_MESSAGE, "inventory_summaries": SELLER_ONLY_MESSAGE, "vendor_sales": None},
            [ORDERS_PATH, SUMMARIES_PATH, REPORTS_PATH],
        ),
        (
            set(),
            None,
            {"orders": None, "inventory_summaries": None, "vendor_sales": MISSING_MARKETPLACES_MESSAGE},
            [ORDERS_PATH, PARTICIPATIONS_PATH, SUMMARIES_PATH, REPORTS_PATH],
        ),
        (
            {PARTICIPATIONS_PATH},
            None,
            {"orders": None, "inventory_summaries": SELLER_ONLY_MESSAGE, "vendor_sales": MISSING_MARKETPLACES_MESSAGE},
            [ORDERS_PATH, PARTICIPATIONS_PATH, REPORTS_PATH],
        ),
    ],
)
def test_probe_endpoint_permissions(
    forbidden_paths: set[str], marketplace_ids: str | None, expected: dict[str, str | None], probed_paths: list[str]
) -> None:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == TOKEN_PATH:
            return TOKEN
        if request.path in forbidden_paths:
            return SP_API_FORBIDDEN
        return PARTICIPATING_IN_A if request.path == PARTICIPATIONS_PATH else ScriptedResponse(json={})

    with scripted_network(respond) as network:
        permissions = probe_endpoint_permissions(
            "na", "client", "secret", "Atzr|refresh", parse_marketplace_ids(marketplace_ids), list(expected)
        )

    assert permissions == expected
    assert [request.path for request in network.requests_log if request.path != TOKEN_PATH] == probed_paths


def test_probes_past_the_setup_budget_leave_access_unknown() -> None:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == TOKEN_PATH:
            return TOKEN
        time.sleep(40)
        return SP_API_FORBIDDEN

    with scripted_network(respond) as network:
        permissions = probe_endpoint_permissions(
            "na", "client", "secret", "Atzr|refresh", ["A"], ["orders", "transactions", "vendor_sales"]
        )

    assert permissions == {"orders": SELLER_ONLY_MESSAGE, "transactions": None, "vendor_sales": None}
    assert [request.path for request in network.requests_log if request.path != TOKEN_PATH] == [ORDERS_PATH]


def test_a_transient_marketplace_discovery_failure_leaves_inventory_access_unknown() -> None:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == TOKEN_PATH:
            return TOKEN
        return ScriptedResponse(status=400, json={"errors": [{"code": "InvalidInput"}]})

    with scripted_network(respond):
        permissions = probe_endpoint_permissions("na", "client", "secret", "Atzr|refresh", [], ["inventory_summaries"])

    assert permissions == {"inventory_summaries": None}
