import gzip
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.amazon_selling_partner import (
    MARKETPLACE_ID_MAX_LENGTH,
    MAX_MARKETPLACE_IDS,
    AmazonSellingPartnerReportError,
    AmazonSellingPartnerResumeConfig,
    AmazonSellingPartnerRetryableError,
    SellingPartnerClient,
    _base_url,
    _extract_next_token,
    _format_timestamp,
    amazon_selling_partner_source,
    get_rows,
    parse_marketplace_ids,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.settings import (
    AMAZON_SELLING_PARTNER_ENDPOINTS,
    ENDPOINTS,
)

_MODULE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.amazon_selling_partner"
)


def _response(
    body: Optional[dict[str, Any]] = None,
    status: int = 200,
    content: Optional[bytes] = None,
) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.json.return_value = body if body is not None else {}
    response.content = content if content is not None else b"{}"
    response.text = ""
    if status >= 400:
        error = requests.HTTPError(f"{status} Client Error", response=response)
        response.raise_for_status.side_effect = error
    else:
        response.raise_for_status.return_value = None
    return response


def _token_provider(*tokens: str) -> mock.MagicMock:
    """Stand in for the integration row: hands back a token, and a fresh one when forced."""
    provider = mock.MagicMock()
    provider.side_effect = list(tokens) if len(tokens) > 1 else None
    provider.return_value = tokens[0] if tokens else "access-token"
    return provider


def _make_manager(resume_state: Optional[AmazonSellingPartnerResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _client(access_token_provider: Optional[mock.MagicMock] = None) -> SellingPartnerClient:
    return SellingPartnerClient("na", access_token_provider or _token_provider())


def _collect(endpoint: str, **kwargs: Any) -> list[list[dict[str, Any]]]:
    params: dict[str, Any] = {
        "region": "na",
        "access_token_provider": _token_provider(),
        "marketplace_ids": "ATVPDKIKX0DER",
        "endpoint": endpoint,
        "logger": mock.MagicMock(),
        "resumable_source_manager": _make_manager(),
    }
    params.update(kwargs)
    return list(get_rows(**params))


@pytest.fixture(autouse=True)
def _instant_retries() -> Iterator[None]:
    """Stop tenacity from actually waiting between the transport's retry attempts."""
    retrying = cast(Any, SellingPartnerClient._request).retry
    original = retrying.sleep
    retrying.sleep = lambda _: None
    yield
    retrying.sleep = original


@pytest.fixture(autouse=True)
def _no_sleep() -> Iterator[None]:
    with mock.patch(f"{_MODULE}.time.sleep"):
        yield


class TestHelpers:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("na", "https://sellingpartnerapi-na.amazon.com"),
            ("eu", "https://sellingpartnerapi-eu.amazon.com"),
            ("fe", "https://sellingpartnerapi-fe.amazon.com"),
        ],
    )
    def test_known_regions_return_correct_host(self, region: str, expected: str) -> None:
        assert _base_url(region) == expected

    def test_unknown_region_raises(self) -> None:
        with pytest.raises(ValueError):
            _base_url("uk")

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("ATVPDKIKX0DER", ["ATVPDKIKX0DER"]),
            ("A1,A2", ["A1", "A2"]),
            (" A1 , A2 ", ["A1", "A2"]),
            ("A1\nA2", ["A1", "A2"]),
            ("A1,A1,A2", ["A1", "A2"]),
        ],
    )
    def test_parse_marketplace_ids(self, raw: str, expected: list[str]) -> None:
        assert parse_marketplace_ids(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", ",,"])
    def test_parse_marketplace_ids_rejects_empty(self, raw: str) -> None:
        with pytest.raises(ValueError):
            parse_marketplace_ids(raw)

    @pytest.mark.parametrize(
        "raw",
        [
            "A1,../../etc/passwd",
            "A1,A2;DROP",
            "A1," + "B" * (MARKETPLACE_ID_MAX_LENGTH + 1),
        ],
    )
    def test_parse_marketplace_ids_rejects_malformed_ids(self, raw: str) -> None:
        with pytest.raises(ValueError, match="Invalid Amazon marketplace ID"):
            parse_marketplace_ids(raw)

    def test_parse_marketplace_ids_rejects_too_many_ids(self) -> None:
        raw = ",".join(f"A{index}" for index in range(MAX_MARKETPLACE_IDS + 1))
        with pytest.raises(ValueError, match="At most"):
            parse_marketplace_ids(raw)

    def test_parse_marketplace_ids_accepts_the_maximum(self) -> None:
        raw = ",".join(f"A{index}" for index in range(MAX_MARKETPLACE_IDS))
        assert len(parse_marketplace_ids(raw)) == MAX_MARKETPLACE_IDS

    def test_parse_marketplace_ids_deduplicates_a_long_list_without_quadratic_scanning(self) -> None:
        # A repeated id is dropped by a set lookup, so a long input stays linear even
        # though the caller controls its length.
        raw = ",".join(["ATVPDKIKX0DER"] * 10_000)
        assert parse_marketplace_ids(raw) == ["ATVPDKIKX0DER"]

    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 5, 1, 12, 30, 0, tzinfo=UTC), "2024-05-01T12:30:00Z"),
            (datetime(2024, 5, 1, 12, 30, 0), "2024-05-01T12:30:00Z"),
            (date(2024, 5, 1), "2024-05-01T00:00:00Z"),
            ("2024-05-01T12:30:00Z", "2024-05-01T12:30:00Z"),
            ("2024-05-01T12:30:00", "2024-05-01T12:30:00Z"),
        ],
    )
    def test_format_timestamp(self, value: Any, expected: str) -> None:
        assert _format_timestamp(value) == expected

    @pytest.mark.parametrize(
        "body, token_param, expected",
        [
            ({"payload": {"Orders": [], "NextToken": "t1"}}, "NextToken", "t1"),
            ({"transactions": [], "nextToken": "t2"}, "nextToken", "t2"),
            ({"payload": {"inventorySummaries": []}, "pagination": {"nextToken": "t3"}}, "nextToken", "t3"),
            ({"payload": {"Orders": []}}, "NextToken", None),
            ({"payload": {"Orders": [], "NextToken": ""}}, "NextToken", None),
        ],
    )
    def test_extract_next_token_handles_every_envelope(
        self, body: dict[str, Any], token_param: str, expected: Optional[str]
    ) -> None:
        assert _extract_next_token(body, token_param) == expected


class TestTokenLifecycle:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_client_session_disables_http_sample_capture(self, mock_session: mock.MagicMock) -> None:
        # Every SP-API call carries a minted `x-amz-access-token` bearer and responses can
        # hold buyer PII, none of which the name-based scrubbers recognise — so the client
        # session must stay out of HTTP sample capture.
        _client()
        assert mock_session.call_args.kwargs["capture"] is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_token_is_cached_rather_than_read_per_request(self, mock_session: mock.MagicMock) -> None:
        # Every request would otherwise hit Postgres for the integration row.
        provider = _token_provider()
        client = _client(provider)

        assert client.access_token() == "access-token"
        assert client.access_token() == "access-token"

        assert provider.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_401_forces_a_fresh_token_and_retries_once(self, mock_session: mock.MagicMock) -> None:
        provider = _token_provider("stale-token", "fresh-token")
        mock_session.return_value.request.side_effect = [
            _response(status=401),
            _response({"payload": {"Orders": []}}),
        ]
        client = _client(provider)

        assert client.request("GET", "/orders/v0/orders") == {"payload": {"Orders": []}}
        assert [call.args[0] for call in provider.call_args_list] == [False, True]
        retried_call = mock_session.return_value.request.call_args_list[1]
        assert retried_call.kwargs["headers"]["x-amz-access-token"] == "fresh-token"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_persistent_401_raises_the_http_error(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.return_value = _response(status=401)
        client = _client()

        with pytest.raises(requests.HTTPError):
            client.request("GET", "/orders/v0/orders")

    @pytest.mark.parametrize("status", [429, 500, 503])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_throttles_and_server_errors_are_retryable(self, mock_session: mock.MagicMock, status: int) -> None:
        mock_session.return_value.request.return_value = _response(status=status)
        client = _client()

        with pytest.raises(AmazonSellingPartnerRetryableError):
            client.request("GET", "/orders/v0/orders")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_transient_error_is_retried_until_it_succeeds(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.side_effect = [
            _response(status=429),
            _response({"payload": {"Orders": []}}),
        ]
        client = _client()

        assert client.request("GET", "/orders/v0/orders") == {"payload": {"Orders": []}}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [
            (200, True),
            # A valid token whose app lacks one role must not block source creation.
            (403, True),
            (400, False),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session: mock.MagicMock, status: int, expected_valid: bool) -> None:
        mock_session.return_value.request.return_value = _response(status=status)

        is_valid, _ = validate_credentials("na", _token_provider())

        assert is_valid is expected_valid

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_token_failure_reports_the_credential_problem(self, mock_session: mock.MagicMock) -> None:
        provider = mock.MagicMock(side_effect=ValueError("Amazon Selling Partner access token not found"))

        is_valid, error = validate_credentials("na", provider)

        assert is_valid is False
        assert error is not None
        assert "Reconnect your Amazon seller account" in error
        mock_session.return_value.request.assert_not_called()

    def test_unknown_region_is_rejected_without_any_request(self) -> None:
        provider = _token_provider()

        is_valid, error = validate_credentials("uk", provider)

        assert is_valid is False
        assert error is not None
        provider.assert_not_called()


class TestOrders:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_with_the_token_alone_after_the_first_page(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.side_effect = [
            _response({"payload": {"Orders": [{"AmazonOrderId": "1"}], "NextToken": "t1"}}),
            _response({"payload": {"Orders": [{"AmazonOrderId": "2"}]}}),
        ]
        manager = _make_manager()

        batches = _collect("orders", resumable_source_manager=manager)

        assert batches == [[{"AmazonOrderId": "1"}], [{"AmazonOrderId": "2"}]]
        first, second = mock_session.return_value.request.call_args_list
        assert first.kwargs["params"]["MarketplaceIds"] == "ATVPDKIKX0DER"
        assert first.kwargs["params"]["MaxResultsPerPage"] == 100
        # Amazon rejects the filters once a continuation token is supplied.
        assert second.kwargs["params"] == {"NextToken": "t1"}
        assert manager.save_state.call_args_list == [mock.call(AmazonSellingPartnerResumeConfig(next_token="t1"))]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_run_sends_the_watermark_as_last_updated_after(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.return_value = _response({"payload": {"Orders": []}})

        _collect(
            "orders",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
        )

        params = mock_session.return_value.request.call_args.kwargs["params"]
        assert params["LastUpdatedAfter"] == "2024-05-01T00:00:00Z"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_sends_no_time_filter(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.return_value = _response({"payload": {"Orders": []}})

        _collect("orders", should_use_incremental_field=False, db_incremental_field_last_value="2024-05-01")

        assert "LastUpdatedAfter" not in mock_session.return_value.request.call_args.kwargs["params"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_the_saved_page_token(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.return_value = _response({"payload": {"Orders": []}})
        manager = _make_manager(AmazonSellingPartnerResumeConfig(next_token="saved"))

        _collect("orders", resumable_source_manager=manager)

        assert mock_session.return_value.request.call_args.kwargs["params"] == {"NextToken": "saved"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_pagination_stops_when_the_token_repeats(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.return_value = _response(
            {"payload": {"Orders": [{"AmazonOrderId": "1"}], "NextToken": "stuck"}}
        )

        batches = _collect("orders")

        assert len(batches) == 2
        assert mock_session.return_value.request.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_page_saves_no_resume_state(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.return_value = _response({"payload": {"Orders": []}})
        manager = _make_manager()

        assert _collect("orders", resumable_source_manager=manager) == []
        manager.save_state.assert_not_called()

    def test_missing_marketplace_id_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            _collect("orders", marketplace_ids="")


class TestOrderItems:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_fans_out_per_order_and_injects_parent_fields(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.side_effect = [
            _response(
                {
                    "payload": {
                        "Orders": [
                            {
                                "AmazonOrderId": "111-1",
                                "LastUpdateDate": "2024-05-02T00:00:00Z",
                                "PurchaseDate": "2024-05-01T00:00:00Z",
                            }
                        ]
                    }
                }
            ),
            _response({"payload": {"OrderItems": [{"OrderItemId": "item-1", "ASIN": "A1"}]}}),
        ]

        batches = _collect("order_items")

        assert batches == [
            [
                {
                    "OrderItemId": "item-1",
                    "ASIN": "A1",
                    "AmazonOrderId": "111-1",
                    "_order_last_update_date": "2024-05-02T00:00:00Z",
                    "_order_purchase_date": "2024-05-01T00:00:00Z",
                }
            ]
        ]
        items_call = mock_session.return_value.request.call_args_list[1]
        assert items_call.args[1].endswith("/orders/v0/orders/111-1/orderItems")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_orders_without_an_id_are_skipped(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.return_value = _response(
            {"payload": {"Orders": [{"OrderStatus": "Shipped"}]}}
        )

        assert _collect("order_items") == []
        assert mock_session.return_value.request.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_parent_watermark_is_pushed_into_the_orders_query(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.return_value = _response({"payload": {"Orders": []}})

        _collect(
            "order_items",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
        )

        assert (
            mock_session.return_value.request.call_args.kwargs["params"]["LastUpdatedAfter"] == "2024-05-01T00:00:00Z"
        )


class TestFbaInventory:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_walks_each_marketplace_and_tags_the_rows(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.side_effect = [
            _response({"payload": {"inventorySummaries": [{"sellerSku": "sku-1"}]}}),
            _response({"payload": {"inventorySummaries": [{"sellerSku": "sku-2"}]}}),
        ]

        batches = _collect("fba_inventory", marketplace_ids="M1,M2")

        assert batches == [
            [{"sellerSku": "sku-1", "_marketplace_id": "M1"}],
            [{"sellerSku": "sku-2", "_marketplace_id": "M2"}],
        ]
        first, second = mock_session.return_value.request.call_args_list
        assert first.kwargs["params"]["granularityId"] == "M1"
        assert first.kwargs["params"]["marketplaceIds"] == "M1"
        assert first.kwargs["params"]["granularityType"] == "Marketplace"
        assert second.kwargs["params"]["granularityId"] == "M2"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_on_the_top_level_pagination_token(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.side_effect = [
            _response(
                {
                    "payload": {"inventorySummaries": [{"sellerSku": "sku-1"}]},
                    "pagination": {"nextToken": "p1"},
                }
            ),
            _response({"payload": {"inventorySummaries": [{"sellerSku": "sku-2"}]}}),
        ]
        manager = _make_manager()

        batches = _collect("fba_inventory", marketplace_ids="M1", resumable_source_manager=manager)

        assert len(batches) == 2
        assert mock_session.return_value.request.call_args_list[1].kwargs["params"] == {"nextToken": "p1"}
        assert manager.save_state.call_args_list == [
            mock.call(AmazonSellingPartnerResumeConfig(next_token="p1", marketplace_id="M1"))
        ]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_skips_the_marketplaces_already_finished(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.return_value = _response({"payload": {"inventorySummaries": []}})
        manager = _make_manager(AmazonSellingPartnerResumeConfig(next_token="saved", marketplace_id="M2"))

        _collect("fba_inventory", marketplace_ids="M1,M2,M3", resumable_source_manager=manager)

        calls = mock_session.return_value.request.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["params"] == {"nextToken": "saved"}
        assert calls[1].kwargs["params"]["granularityId"] == "M3"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_token_for_an_unknown_marketplace_is_discarded(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.return_value = _response({"payload": {"inventorySummaries": []}})
        manager = _make_manager(AmazonSellingPartnerResumeConfig(next_token="saved", marketplace_id="GONE"))

        _collect("fba_inventory", marketplace_ids="M1", resumable_source_manager=manager)

        assert mock_session.return_value.request.call_args.kwargs["params"]["granularityId"] == "M1"


def _report_document_bytes(rows: list[dict[str, Any]]) -> bytes:
    return gzip.compress(json.dumps({"salesAndTrafficByDate": rows}).encode())


class TestSalesAndTrafficReport:
    def _recent_watermark(self) -> datetime:
        return datetime.now(UTC) - timedelta(days=5)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_creates_polls_downloads_and_yields_rows(self, mock_session: mock.MagicMock) -> None:
        rows = [{"date": "2024-05-01", "salesByDate": {}, "trafficByDate": {}}]
        mock_session.return_value.request.side_effect = [
            _response({"reportId": "R1"}),
            _response({"processingStatus": "IN_QUEUE"}),
            _response({"processingStatus": "DONE", "reportDocumentId": "D1"}),
            _response({"url": "https://s3.example/doc", "compressionAlgorithm": "GZIP"}),
        ]
        mock_session.return_value.get.return_value = _response(content=_report_document_bytes(rows))
        manager = _make_manager()

        batches = _collect(
            "sales_and_traffic",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=self._recent_watermark(),
        )

        assert batches == [rows]
        create_call = mock_session.return_value.request.call_args_list[0]
        assert create_call.args[0] == "POST"
        assert create_call.kwargs["json"]["reportType"] == "GET_SALES_AND_TRAFFIC_REPORT"
        assert create_call.kwargs["json"]["marketplaceIds"] == ["ATVPDKIKX0DER"]
        assert create_call.kwargs["json"]["reportOptions"] == {"dateGranularity": "DAY", "asinGranularity": "PARENT"}
        # The in-flight report id is checkpointed so a resume doesn't recreate the job.
        assert any(call.args[0].report_id == "R1" for call in manager.save_state.call_args_list)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_report_download_disables_http_sample_capture(self, mock_session: mock.MagicMock) -> None:
        rows = [{"date": "2024-05-01"}]
        mock_session.return_value.request.side_effect = [
            _response({"reportId": "R1"}),
            _response({"processingStatus": "DONE", "reportDocumentId": "D1"}),
            _response({"url": "https://s3.example/doc"}),
        ]
        mock_session.return_value.get.return_value = _response(
            content=json.dumps({"salesAndTrafficByDate": rows}).encode()
        )

        _collect(
            "sales_and_traffic",
            should_use_incremental_field=True,
            db_incremental_field_last_value=self._recent_watermark(),
        )

        # The report body is buyer PII and the presigned URL carries AWS signing creds, so
        # the download session must stay out of HTTP sample capture just like the client's.
        assert mock_session.call_count >= 2
        assert all(call.kwargs.get("capture") is False for call in mock_session.call_args_list)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_download_failure_does_not_leak_the_presigned_url(self, mock_session: mock.MagicMock) -> None:
        presigned = (
            "https://s3.example/doc?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            "&X-Amz-Credential=AKIAEXAMPLEKEYID%2F20240501%2Fus-east-1%2Fs3%2Faws4_request"
            "&X-Amz-Security-Token=FwoGZXIvYXdzEXAMPLESESSIONTOKEN"
            "&X-Amz-Signature=6fc0e5a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d"
        )
        mock_session.return_value.request.side_effect = [
            _response({"reportId": "R1"}),
            _response({"processingStatus": "DONE", "reportDocumentId": "D1"}),
            _response({"url": presigned}),
        ]
        # What `requests` actually raises: the message carries the whole request URL.
        mock_session.return_value.get.side_effect = requests.HTTPError(
            f"403 Client Error for url: {presigned}", response=_response(status=403)
        )

        with pytest.raises(AmazonSellingPartnerReportError) as excinfo:
            _collect(
                "sales_and_traffic",
                should_use_incremental_field=True,
                db_incremental_field_last_value=self._recent_watermark(),
            )

        message = str(excinfo.value)
        assert "D1" in message and "HTTPError" in message
        for secret in ("X-Amz-Signature=6fc0e5a1", "AKIAEXAMPLEKEYID", "FwoGZXIvYXdzEXAMPLESESSIONTOKEN"):
            assert secret not in message
        # The original exception is suppressed so its message can't be re-read off `__cause__`.
        assert excinfo.value.__cause__ is None

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_uncompressed_document_is_parsed_too(self, mock_session: mock.MagicMock) -> None:
        rows = [{"date": "2024-05-01"}]
        mock_session.return_value.request.side_effect = [
            _response({"reportId": "R1"}),
            _response({"processingStatus": "DONE", "reportDocumentId": "D1"}),
            _response({"url": "https://s3.example/doc"}),
        ]
        mock_session.return_value.get.return_value = _response(
            content=json.dumps({"salesAndTrafficByDate": rows}).encode()
        )

        batches = _collect(
            "sales_and_traffic",
            should_use_incremental_field=True,
            db_incremental_field_last_value=self._recent_watermark(),
        )

        assert batches == [rows]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_cancelled_report_yields_nothing(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.side_effect = [
            _response({"reportId": "R1"}),
            _response({"processingStatus": "CANCELLED"}),
        ]

        batches = _collect(
            "sales_and_traffic",
            should_use_incremental_field=True,
            db_incremental_field_last_value=self._recent_watermark(),
        )

        assert batches == []

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_fatal_report_raises(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.side_effect = [
            _response({"reportId": "R1"}),
            _response({"processingStatus": "FATAL"}),
        ]

        with pytest.raises(AmazonSellingPartnerReportError):
            _collect(
                "sales_and_traffic",
                should_use_incremental_field=True,
                db_incremental_field_last_value=self._recent_watermark(),
            )

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_reuses_the_in_flight_report(self, mock_session: mock.MagicMock) -> None:
        window_start = _format_timestamp(self._recent_watermark())
        mock_session.return_value.request.side_effect = [
            _response({"processingStatus": "DONE", "reportDocumentId": "D1"}),
            _response({"url": "https://s3.example/doc", "compressionAlgorithm": "GZIP"}),
        ]
        mock_session.return_value.get.return_value = _response(content=_report_document_bytes([{"date": "2024-05-01"}]))
        manager = _make_manager(AmazonSellingPartnerResumeConfig(window_start=window_start, report_id="R-existing"))

        batches = _collect("sales_and_traffic", resumable_source_manager=manager)

        assert batches == [[{"date": "2024-05-01"}]]
        status_call = mock_session.return_value.request.call_args_list[0]
        assert status_call.args[0] == "GET"
        assert status_call.args[1].endswith("/reports/2021-06-30/reports/R-existing")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_backfill_is_sliced_into_windows(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.side_effect = [
            _response({"reportId": "R1"}),
            _response({"processingStatus": "CANCELLED"}),
            _response({"reportId": "R2"}),
            _response({"processingStatus": "CANCELLED"}),
        ]

        _collect(
            "sales_and_traffic",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now(UTC) - timedelta(days=45),
        )

        create_calls = [call for call in mock_session.return_value.request.call_args_list if call.args[0] == "POST"]
        assert len(create_calls) == 2
        # Consecutive windows must abut, so no day falls between two report jobs.
        assert create_calls[0].kwargs["json"]["dataEndTime"] == create_calls[1].kwargs["json"]["dataStartTime"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_report_that_never_finishes_becomes_retryable(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.request.side_effect = [_response({"reportId": "R1"})] + [
            _response({"processingStatus": "IN_PROGRESS"}) for _ in range(200)
        ]

        with pytest.raises(AmazonSellingPartnerRetryableError):
            _collect(
                "sales_and_traffic",
                should_use_incremental_field=True,
                db_incremental_field_last_value=self._recent_watermark(),
            )


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_matches_the_endpoint_catalog(self, endpoint: str) -> None:
        config = AMAZON_SELLING_PARTNER_ENDPOINTS[endpoint]

        response = amazon_selling_partner_source(
            region="na",
            access_token_provider=_token_provider(),
            marketplace_ids="ATVPDKIKX0DER",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=_make_manager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == config.sort_mode
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
