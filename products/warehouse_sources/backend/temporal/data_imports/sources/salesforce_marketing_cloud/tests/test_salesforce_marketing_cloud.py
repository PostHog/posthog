from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.salesforce_marketing_cloud import (
    PARTNER_NS,
    SalesforceMarketingCloudAuthError,
    SalesforceMarketingCloudClient,
    SalesforceMarketingCloudError,
    SalesforceMarketingCloudResumeConfig,
    SalesforceMarketingCloudRetryableError,
    build_retrieve_envelope,
    format_soap_datetime,
    get_rows,
    normalize_subdomain,
    parse_retrieve_response,
    salesforce_marketing_cloud_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.settings import (
    REST_PAGE_SIZE,
    SALESFORCE_MARKETING_CLOUD_ENDPOINTS,
)


class FakeResumeManager(ResumableSourceManager[SalesforceMarketingCloudResumeConfig]):
    """In-memory stand-in for the Redis-backed manager."""

    def __init__(self, state: SalesforceMarketingCloudResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[SalesforceMarketingCloudResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> SalesforceMarketingCloudResumeConfig | None:
        return self.state

    def save_state(self, data: SalesforceMarketingCloudResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True

    def with_namespace(self, namespace: str) -> "FakeResumeManager":
        return self


def _logger() -> Any:
    return MagicMock()


def _soap_response(status: str, request_id: str | None, rows_xml: str) -> str:
    request_id_node = f"<RequestID>{request_id}</RequestID>" if request_id else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<soap:Body>"
        f'<RetrieveResponseMsg xmlns="{PARTNER_NS}">'
        f"<OverallStatus>{status}</OverallStatus>"
        f"{request_id_node}"
        f"{rows_xml}"
        "</RetrieveResponseMsg>"
        "</soap:Body></soap:Envelope>"
    )


def _open_event_rows(count: int, start: int = 0) -> str:
    return "".join(
        (
            '<Results xsi:type="OpenEvent">'
            f"<SendID>{100 + index}</SendID>"
            f"<SubscriberKey>sub-{index}</SubscriberKey>"
            "<EventDate>2024-03-01T10:00:00</EventDate>"
            "<EventType>Open</EventType>"
            '<BatchID xsi:nil="true"/>'
            "</Results>"
        )
        for index in range(start, start + count)
    )


def _mock_http_response(status_code: int, *, text: str = "", json_body: Any = None) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = status_code < 400
    response.text = text
    response.json.return_value = json_body if json_body is not None else {}

    def raise_for_status() -> None:
        if not response.ok:
            raise requests.HTTPError(f"{status_code} Client Error", response=response)

    response.raise_for_status.side_effect = raise_for_status
    return response


def _client(session: MagicMock) -> SalesforceMarketingCloudClient:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.salesforce_marketing_cloud.make_tracked_session",
        return_value=session,
    ):
        return SalesforceMarketingCloudClient("tenant123", "cid", "csecret", None, _logger())


def _token_response(expires_in: int = 1200, **extra: Any) -> MagicMock:
    return _mock_http_response(200, json_body={"access_token": "tok", "expires_in": expires_in, **extra})


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare", "mc563885gzs27c5t9-63k636ttgm", "mc563885gzs27c5t9-63k636ttgm"),
            ("auth_host", "mc123-abc.auth.marketingcloudapis.com", "mc123-abc"),
            ("rest_url", "https://mc123-abc.rest.marketingcloudapis.com/", "mc123-abc"),
            ("soap_url", "https://mc123-abc.soap.marketingcloudapis.com/Service.asmx", "mc123-abc"),
            ("whitespace_and_case", "  MC123-ABC  ", "mc123-abc"),
        ]
    )
    def test_accepts_the_forms_users_paste(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected

    @parameterized.expand([("empty", ""), ("underscore", "mc_123"), ("dot", "mc.123"), ("space", "mc 123")])
    def test_rejects_invalid_subdomains(self, _name: str, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_subdomain(raw)


class TestFormatSoapDatetime:
    @parameterized.expand(
        [
            ("naive_datetime", datetime(2024, 3, 1, 10, 30, 15), "2024-03-01T10:30:15"),
            ("aware_datetime_converted_to_utc", datetime(2024, 3, 1, 10, 30, 15, tzinfo=UTC), "2024-03-01T10:30:15"),
            ("date", date(2024, 3, 1), "2024-03-01T00:00:00"),
            ("iso_string", "2024-03-01T10:30:15+00:00", "2024-03-01T10:30:15"),
            ("zulu_string", "2024-03-01T10:30:15Z", "2024-03-01T10:30:15"),
        ]
    )
    def test_formats_watermarks_without_a_timezone_suffix(self, _name: str, value: Any, expected: str) -> None:
        assert format_soap_datetime(value) == expected

    @parameterized.expand([("none", None), ("empty", ""), ("garbage", "not-a-date"), ("number", 12345)])
    def test_returns_none_for_unusable_values(self, _name: str, value: Any) -> None:
        assert format_soap_datetime(value) is None


class TestRetrieveEnvelope:
    def test_first_page_carries_object_type_properties_and_token(self) -> None:
        envelope = build_retrieve_envelope("OpenEvent", ("SendID", "EventDate"), "tok")

        assert "<ObjectType>OpenEvent</ObjectType>" in envelope
        assert "<Properties>SendID</Properties><Properties>EventDate</Properties>" in envelope
        assert '<fueloauth xmlns="http://exacttarget.com">tok</fueloauth>' in envelope
        assert "ContinueRequest" not in envelope
        assert "SimpleFilterPart" not in envelope

    def test_incremental_filter_uses_greater_than_on_the_chosen_property(self) -> None:
        envelope = build_retrieve_envelope(
            "OpenEvent", ("SendID",), "tok", filter_property="EventDate", filter_value="2024-03-01T00:00:00"
        )

        assert '<Filter xsi:type="SimpleFilterPart">' in envelope
        assert "<Property>EventDate</Property>" in envelope
        assert "<SimpleOperator>greaterThan</SimpleOperator>" in envelope
        assert "<Value>2024-03-01T00:00:00</Value>" in envelope

    def test_continuation_repeats_properties_but_drops_the_filter(self) -> None:
        # The partner API rejects a ContinueRequest that omits ObjectType/Properties, and it keeps
        # the original filter server-side — resending it would be an error.
        envelope = build_retrieve_envelope(
            "OpenEvent",
            ("SendID",),
            "tok",
            filter_property="EventDate",
            filter_value="2024-03-01T00:00:00",
            continue_request="req-1",
        )

        assert "<ContinueRequest>req-1</ContinueRequest>" in envelope
        assert "<ObjectType>OpenEvent</ObjectType>" in envelope
        assert "<Properties>SendID</Properties>" in envelope
        assert "SimpleFilterPart" not in envelope

    def test_values_are_xml_escaped(self) -> None:
        envelope = build_retrieve_envelope("List", ("ID",), "tok&<>", filter_property="ListName", filter_value="A & B")

        assert "tok&amp;&lt;&gt;" in envelope
        assert "<Value>A &amp; B</Value>" in envelope


class TestParseRetrieveResponse:
    def test_flattens_results_and_reports_continuation(self) -> None:
        status, request_id, rows = parse_retrieve_response(
            _soap_response("MoreDataAvailable", "req-9", _open_event_rows(2))
        )

        assert status == "MoreDataAvailable"
        assert request_id == "req-9"
        assert rows == [
            {
                "SendID": "100",
                "SubscriberKey": "sub-0",
                "EventDate": "2024-03-01T10:00:00",
                "EventType": "Open",
                "BatchID": None,
            },
            {
                "SendID": "101",
                "SubscriberKey": "sub-1",
                "EventDate": "2024-03-01T10:00:00",
                "EventType": "Open",
                "BatchID": None,
            },
        ]

    def test_nested_complex_types_are_flattened_with_an_underscore(self) -> None:
        rows_xml = (
            '<Results xsi:type="DataExtensionField">'
            "<ObjectID>obj-1</ObjectID>"
            "<DataExtension><CustomerKey>DE_KEY</CustomerKey></DataExtension>"
            "</Results>"
        )

        _status, _request_id, rows = parse_retrieve_response(_soap_response("OK", None, rows_xml))

        assert rows == [{"ObjectID": "obj-1", "DataExtension_CustomerKey": "DE_KEY"}]

    def test_error_status_raises_with_the_status_message(self) -> None:
        rows_xml = "<Results><StatusMessage>Unable to find property EventDate</StatusMessage></Results>"

        with pytest.raises(SalesforceMarketingCloudError, match="Unable to find property EventDate"):
            parse_retrieve_response(_soap_response("Error", None, rows_xml))

    def test_soap_fault_raises(self) -> None:
        fault = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
            "<soap:Fault><faultstring>Token expired</faultstring></soap:Fault>"
            "</soap:Body></soap:Envelope>"
        )

        with pytest.raises(SalesforceMarketingCloudError, match="Token expired"):
            parse_retrieve_response(fault)

    def test_unrecognised_body_raises(self) -> None:
        with pytest.raises(SalesforceMarketingCloudError, match="unrecognised"):
            parse_retrieve_response("<html><body>maintenance</body></html>")


class TestTokenMinting:
    def test_token_response_endpoints_override_the_derived_hosts(self) -> None:
        session = MagicMock()
        session.post.return_value = _token_response(
            rest_instance_url="https://relocated.rest.marketingcloudapis.com/",
            soap_instance_url="https://relocated.soap.marketingcloudapis.com/",
        )
        client = _client(session)

        client.mint_token()

        assert client.rest_base_url == "https://relocated.rest.marketingcloudapis.com"
        assert client.soap_url == "https://relocated.soap.marketingcloudapis.com/Service.asmx"

    def test_derived_hosts_are_used_when_the_response_omits_them(self) -> None:
        session = MagicMock()
        session.post.return_value = _token_response()
        client = _client(session)

        client.mint_token()

        assert client.rest_base_url == "https://tenant123.rest.marketingcloudapis.com"
        assert client.soap_url == "https://tenant123.soap.marketingcloudapis.com/Service.asmx"
        assert client.auth_url == "https://tenant123.auth.marketingcloudapis.com/v2/token"

    def test_account_id_is_sent_only_when_supplied(self) -> None:
        session = MagicMock()
        session.post.return_value = _token_response()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.salesforce_marketing_cloud.make_tracked_session",
            return_value=session,
        ):
            SalesforceMarketingCloudClient("tenant123", "cid", "csecret", "7654321").mint_token()

        assert session.post.call_args.kwargs["json"]["account_id"] == "7654321"

        session.post.reset_mock()
        session.post.return_value = _token_response()
        _client(session).mint_token()

        assert "account_id" not in session.post.call_args.kwargs["json"]

    def test_token_is_reused_until_it_nears_expiry(self) -> None:
        session = MagicMock()
        session.post.return_value = _token_response(expires_in=1200)
        client = _client(session)

        assert client.access_token() == "tok"
        assert client.access_token() == "tok"

        assert session.post.call_count == 1

    def test_expired_token_is_reminted_on_the_next_call(self) -> None:
        # Marketing Cloud tokens last 20 minutes with no refresh token, so a sync that outlives one
        # must mint a new one rather than keep sending a dead bearer token.
        session = MagicMock()
        session.post.return_value = _token_response(expires_in=1200)
        client = _client(session)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.salesforce_marketing_cloud.time.monotonic",
            side_effect=[0.0, 5000.0, 5000.0],
        ):
            client.access_token()
            client.access_token()

        assert session.post.call_count == 2

    def test_forced_refresh_mints_a_new_token(self) -> None:
        session = MagicMock()
        session.post.return_value = _token_response()
        client = _client(session)

        client.access_token()
        client.access_token(force_refresh=True)

        assert session.post.call_count == 2

    @parameterized.expand([("bad_request", 400), ("unauthorized", 401), ("forbidden", 403)])
    def test_credential_rejections_raise_auth_error(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.post.return_value = _mock_http_response(status_code, text="invalid_client")
        client = _client(session)

        with pytest.raises(SalesforceMarketingCloudAuthError) as exc_info:
            client.mint_token()

        assert exc_info.value.status_code == status_code

    @parameterized.expand([("throttled", 429), ("bad_gateway", 502)])
    def test_transient_token_errors_are_retryable(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.post.return_value = _mock_http_response(status_code)
        client = _client(session)

        with pytest.raises(SalesforceMarketingCloudRetryableError):
            client.mint_token()

    def test_token_response_without_an_access_token_is_an_auth_error(self) -> None:
        session = MagicMock()
        session.post.return_value = _mock_http_response(200, json_body={"expires_in": 1200})
        client = _client(session)

        with pytest.raises(SalesforceMarketingCloudAuthError):
            client.mint_token()


class TestRestRequests:
    def test_expired_token_is_reminted_once_and_the_call_replayed(self) -> None:
        session = MagicMock()
        session.post.return_value = _token_response()
        session.get.side_effect = [
            _mock_http_response(401, text="expired"),
            _mock_http_response(200, json_body={"items": [{"id": "a"}], "count": 1}),
        ]
        client = _client(session)

        body = client.rest_get("/asset/v1/content/assets", {"$page": 1})

        assert body == {"items": [{"id": "a"}], "count": 1}
        assert session.post.call_count == 2  # initial mint + forced re-mint

    def test_persistent_401_surfaces_as_an_auth_error(self) -> None:
        session = MagicMock()
        session.post.return_value = _token_response()
        session.get.return_value = _mock_http_response(401, text="nope")
        client = _client(session)

        with pytest.raises(SalesforceMarketingCloudAuthError):
            client.rest_get("/asset/v1/content/assets", {"$page": 1})

    def test_forbidden_surfaces_as_an_auth_error(self) -> None:
        session = MagicMock()
        session.post.return_value = _token_response()
        session.get.return_value = _mock_http_response(403, text="missing scope")
        client = _client(session)

        with pytest.raises(SalesforceMarketingCloudAuthError):
            client.rest_get("/asset/v1/content/assets", {"$page": 1})


class TestSoapPagination:
    def _session(self, responses: list[str]) -> MagicMock:
        session = MagicMock()
        session.post.side_effect = [_token_response(), *[_mock_http_response(200, text=xml) for xml in responses]]
        return session

    def _rows(self, endpoint: str, session: MagicMock, manager: FakeResumeManager, **kwargs: Any) -> list[list[dict]]:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.salesforce_marketing_cloud.make_tracked_session",
            return_value=session,
        ):
            return list(
                get_rows(
                    subdomain="tenant123",
                    client_id="cid",
                    client_secret="csecret",
                    account_id=None,
                    endpoint=endpoint,
                    logger=_logger(),
                    resumable_source_manager=manager,
                    **kwargs,
                )
            )

    def test_continues_until_status_is_ok(self) -> None:
        session = self._session(
            [
                _soap_response("MoreDataAvailable", "req-1", _open_event_rows(2)),
                _soap_response("OK", None, _open_event_rows(1, start=2)),
            ]
        )
        manager = FakeResumeManager()

        batches = self._rows("open_events", session, manager)

        assert [len(batch) for batch in batches] == [2, 1]
        # State is saved only while more data is pending, and cleared once the walk completes.
        assert [state.request_id for state in manager.saved] == ["req-1"]
        assert manager.cleared is True

    def test_more_data_without_a_request_id_terminates(self) -> None:
        # Defensive: a MoreDataAvailable with no continuation token would otherwise loop forever
        # re-fetching the first batch.
        session = self._session([_soap_response("MoreDataAvailable", None, _open_event_rows(1))])
        manager = FakeResumeManager()

        batches = self._rows("open_events", session, manager)

        assert len(batches) == 1
        assert manager.saved == []

    def test_resume_starts_from_the_saved_continuation_token(self) -> None:
        session = self._session([_soap_response("OK", None, _open_event_rows(1))])
        manager = FakeResumeManager(SalesforceMarketingCloudResumeConfig(request_id="req-saved"))

        self._rows(
            "open_events",
            session,
            manager,
            incremental_field="EventDate",
            db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
        )

        envelope = session.post.call_args_list[-1].kwargs["data"].decode()
        assert "<ContinueRequest>req-saved</ContinueRequest>" in envelope
        # A resumed walk must not re-apply the filter — the server already scoped the request.
        assert "SimpleFilterPart" not in envelope

    def test_incremental_sync_filters_on_the_users_chosen_field(self) -> None:
        session = self._session([_soap_response("OK", None, _open_event_rows(1))])

        self._rows(
            "open_events",
            session,
            FakeResumeManager(),
            incremental_field="EventDate",
            db_incremental_field_last_value=datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC),
        )

        envelope = session.post.call_args_list[-1].kwargs["data"].decode()
        assert "<Property>EventDate</Property>" in envelope
        assert "<Value>2024-03-01T12:00:00</Value>" in envelope

    def test_unknown_incremental_field_falls_back_to_the_endpoint_default(self) -> None:
        session = self._session([_soap_response("OK", None, _open_event_rows(1))])

        self._rows(
            "open_events",
            session,
            FakeResumeManager(),
            incremental_field="NotARealProperty",
            db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
        )

        envelope = session.post.call_args_list[-1].kwargs["data"].decode()
        assert "<Property>EventDate</Property>" in envelope

    def test_full_refresh_sends_no_filter(self) -> None:
        session = self._session([_soap_response("OK", None, _open_event_rows(1))])

        self._rows("open_events", session, FakeResumeManager())

        envelope = session.post.call_args_list[-1].kwargs["data"].decode()
        assert "SimpleFilterPart" not in envelope

    def test_soap_action_header_is_retrieve(self) -> None:
        session = self._session([_soap_response("OK", None, _open_event_rows(1))])

        self._rows("open_events", session, FakeResumeManager())

        headers = session.post.call_args_list[-1].kwargs["headers"]
        assert headers["SOAPAction"] == "Retrieve"
        assert headers["Content-Type"] == "text/xml; charset=utf-8"


class TestRestPagination:
    def _rows(self, endpoint: str, pages: list[dict], manager: FakeResumeManager) -> list[list[dict]]:
        session = MagicMock()
        session.post.return_value = _token_response()
        session.get.side_effect = [_mock_http_response(200, json_body=page) for page in pages]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.salesforce_marketing_cloud.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    subdomain="tenant123",
                    client_id="cid",
                    client_secret="csecret",
                    account_id=None,
                    endpoint=endpoint,
                    logger=_logger(),
                    resumable_source_manager=manager,
                )
            )
        self.session = session
        return batches

    def test_stops_when_the_reported_count_is_reached(self) -> None:
        manager = FakeResumeManager()
        pages = [
            {"items": [{"id": index} for index in range(REST_PAGE_SIZE)], "count": REST_PAGE_SIZE + 1},
            {"items": [{"id": "last"}], "count": REST_PAGE_SIZE + 1},
        ]

        batches = self._rows("assets", pages, manager)

        assert [len(batch) for batch in batches] == [REST_PAGE_SIZE, 1]
        assert [state.page for state in manager.saved] == [2]
        assert manager.cleared is True

    def test_stops_on_a_short_page_when_no_count_is_reported(self) -> None:
        batches = self._rows("journeys", [{"items": [{"id": "a", "version": 1}]}], FakeResumeManager())

        assert batches == [[{"id": "a", "version": 1}]]

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = FakeResumeManager()

        assert self._rows("campaigns", [{"items": [], "count": 0}], manager) == []
        assert manager.cleared is True

    def test_resume_starts_from_the_saved_page(self) -> None:
        manager = FakeResumeManager(SalesforceMarketingCloudResumeConfig(page=3))

        self._rows("assets", [{"items": [{"id": "x"}], "count": 200}], manager)

        assert self.session.get.call_args_list[0].args[0].endswith("%24page=3&%24pageSize=50")


class TestValidateCredentials:
    def test_returns_true_when_a_token_is_minted(self) -> None:
        session = MagicMock()
        session.post.return_value = _token_response()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.salesforce_marketing_cloud.make_tracked_session",
            return_value=session,
        ):
            assert validate_credentials("tenant123", "cid", "csecret", None) == (True, None)

    def test_rejected_credentials_return_an_actionable_message(self) -> None:
        session = MagicMock()
        session.post.return_value = _mock_http_response(401, text="invalid_client")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.salesforce_marketing_cloud.make_tracked_session",
            return_value=session,
        ):
            ok, message = validate_credentials("tenant123", "cid", "csecret", None)

        assert ok is False
        assert message is not None and "client ID" in message

    def test_invalid_subdomain_is_reported_without_a_network_call(self) -> None:
        ok, message = validate_credentials("not a subdomain", "cid", "csecret", None)

        assert ok is False
        assert message is not None and "subdomain" in message

    def test_network_failure_is_not_reported_as_bad_credentials(self) -> None:
        session = MagicMock()
        session.post.side_effect = requests.ConnectionError("boom")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.salesforce_marketing_cloud.make_tracked_session",
            return_value=session,
        ):
            ok, message = validate_credentials("tenant123", "cid", "csecret", None)

        assert ok is False
        assert message == "Could not reach Salesforce Marketing Cloud with the details provided."


class TestSourceResponse:
    @parameterized.expand(sorted(SALESFORCE_MARKETING_CLOUD_ENDPOINTS))
    def test_response_matches_the_endpoint_catalog(self, endpoint: str) -> None:
        config = SALESFORCE_MARKETING_CLOUD_ENDPOINTS[endpoint]

        response = salesforce_marketing_cloud_source(
            subdomain="tenant123",
            client_id="cid",
            client_secret="csecret",
            account_id=None,
            endpoint=endpoint,
            logger=_logger(),
            resumable_source_manager=FakeResumeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None

    @parameterized.expand(sorted(SALESFORCE_MARKETING_CLOUD_ENDPOINTS))
    def test_soap_endpoints_defer_the_watermark_to_the_end_of_the_run(self, endpoint: str) -> None:
        # SOAP Retrieve batches arrive in no guaranteed order, so "desc" (max-at-completion) is the
        # only safe watermark mode; declaring "asc" would checkpoint a value rows may still precede.
        config = SALESFORCE_MARKETING_CLOUD_ENDPOINTS[endpoint]

        response = salesforce_marketing_cloud_source(
            subdomain="tenant123",
            client_id="cid",
            client_secret="csecret",
            account_id=None,
            endpoint=endpoint,
            logger=_logger(),
            resumable_source_manager=FakeResumeManager(),
        )

        assert response.sort_mode == ("desc" if config.transport == "soap" else "asc")

    def test_items_are_lazy(self) -> None:
        # Building the response must not touch the network; the pipeline calls items() later.
        response = salesforce_marketing_cloud_source(
            subdomain="tenant123",
            client_id="cid",
            client_secret="csecret",
            account_id=None,
            endpoint="open_events",
            logger=_logger(),
            resumable_source_manager=FakeResumeManager(),
        )

        assert callable(response.items)


class TestSourceInputsPlumbing:
    def test_incremental_values_are_dropped_when_the_schema_is_full_refresh(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.salesforcemarketingcloud import (
            SalesforceMarketingCloudSourceConfig,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.source import (
            SalesforceMarketingCloudSource,
        )

        inputs = SourceInputs(
            schema_name="open_events",
            schema_id="schema-1",
            source_id="source-1",
            team_id=1,
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
            db_incremental_field_earliest_value=None,
            incremental_field="EventDate",
            incremental_field_type=None,
            job_id="job-1",
            logger=_logger(),
            reset_pipeline=False,
        )
        config = SalesforceMarketingCloudSourceConfig(
            subdomain="tenant123", client_id="cid", client_secret="csecret", account_id=None
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.source.salesforce_marketing_cloud_source"
        ) as mocked:
            SalesforceMarketingCloudSource().source_for_pipeline(config, FakeResumeManager(), inputs)

        assert mocked.call_args.kwargs["incremental_field"] is None
        assert mocked.call_args.kwargs["db_incremental_field_last_value"] is None


class TestRowsAreDicts:
    def test_soap_rows_are_plain_dicts_ready_for_the_pipeline(self) -> None:
        session = MagicMock()
        session.post.side_effect = [
            _token_response(),
            _mock_http_response(200, text=_soap_response("OK", None, _open_event_rows(1))),
        ]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.salesforce_marketing_cloud.make_tracked_session",
            return_value=session,
        ):
            response = salesforce_marketing_cloud_source(
                subdomain="tenant123",
                client_id="cid",
                client_secret="csecret",
                account_id=None,
                endpoint="open_events",
                logger=_logger(),
                resumable_source_manager=FakeResumeManager(),
            )
            batches = list(cast("Iterable[Any]", response.items()))

        assert batches == [
            [
                {
                    "SendID": "100",
                    "SubscriberKey": "sub-0",
                    "EventDate": "2024-03-01T10:00:00",
                    "EventType": "Open",
                    "BatchID": None,
                }
            ]
        ]
