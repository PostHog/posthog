import io
import gzip
import json
import datetime as dt
from collections.abc import Callable, Iterator
from typing import Any, Literal

import pytest
import time_machine

import requests

from products.warehouse_sources.sources.amazon_ads._config import AmazonAdsSourceConfig
from products.warehouse_sources.sources.amazon_ads.amazon_ads import (
    INVALID_REGION_MESSAGE,
    LWA_REJECTED_MESSAGE,
    LWA_TOKEN_URL,
    PROFILES_DENIED_MESSAGE,
    REPORT_POLL_BUDGET_SECONDS,
    REPORT_POLL_INTERVAL_SECONDS,
    UNAVAILABLE_MESSAGE,
    AmazonAdsReportError,
    AmazonAdsResumeConfig,
    AmazonAdsRetryableError,
    _base_url,
    iter_json_array,
    validate_credentials,
)
from products.warehouse_sources.sources.amazon_ads.settings import (
    AMAZON_ADS_ENDPOINTS,
    ENDPOINTS,
    HISTORY_EVENT_TYPES,
    HISTORY_LOOKBACK_MS,
    HISTORY_PAGE_SIZE,
    HISTORY_RETENTION_DAYS,
    PAGE_SIZE,
    SP_CAMPAIGN_REPORT,
)
from products.warehouse_sources.sources.amazon_ads.source import AmazonAdsSource
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    error_message_matches,
    scripted_network,
)

_REPORT_URL = "https://offline-report-storage.s3.amazonaws.com/report.json.gz"
_TODAY = "2026-06-30"
_NOW_MS = int(dt.datetime(2026, 6, 30, tzinfo=dt.UTC).timestamp() * 1000)
_HISTORY_EARLIEST_MS = _NOW_MS - HISTORY_RETENTION_DAYS * 24 * 60 * 60 * 1000


def _driver() -> SourceDriver:
    return SourceDriver(
        AmazonAdsSource(),
        AmazonAdsSourceConfig(region="na", client_id="cid", client_secret="sec", refresh_token="rt"),
    )


def _token() -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "the-token", "expires_in": 3600})


def _profiles(profiles: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json=profiles)


def _report_script(
    rows: list[dict[str, Any]],
    poll_statuses: list[str] | None = None,
    report_url: str = _REPORT_URL,
) -> Callable[[RecordedRequest], ScriptedResponse]:
    created = 0
    polls = 0
    statuses = poll_statuses or ["COMPLETED"]

    def respond(request: RecordedRequest) -> ScriptedResponse:
        nonlocal created, polls
        if request.url == LWA_TOKEN_URL:
            return _token()
        if request.path == "/v2/profiles":
            return _profiles([{"profileId": 7}])
        if request.path == "/reporting/reports" and request.method == "POST":
            created += 1
            return ScriptedResponse(json={"reportId": f"rep-{created}"})
        if request.path.startswith("/reporting/reports/"):
            status = statuses[min(polls, len(statuses) - 1)]
            polls += 1
            return ScriptedResponse(json={"status": status, "url": report_url if status == "COMPLETED" else None})
        if request.url == _REPORT_URL:
            return ScriptedResponse(body=gzip.compress(json.dumps(rows).encode()))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    return respond


def _report_requests(requests: list[RecordedRequest]) -> list[RecordedRequest]:
    return [request for request in requests if request.path == "/reporting/reports" and request.method == "POST"]


class TestIterJsonArray:
    _DOCUMENT = (
        ' [ {"date": "2026-06-20", "cost": 12.5, "searchTerm": "a, [b] {c}"},\n'
        '{"nested": {"list": [1, 2, {"x": null}]}, "clicks": 1234567}, 9876543,'
        '{"quote": "say \\"hi\\"", "unicode": "caf\u00e9"} ]  '
    )

    @pytest.mark.parametrize("chunk_size", [1, 2, 7, 64, 1024 * 1024])
    def test_streams_the_same_elements_as_a_whole_document_parse(self, chunk_size: int) -> None:
        stream = io.BytesIO(self._DOCUMENT.encode())
        assert list(iter_json_array(stream, chunk_size=chunk_size)) == json.loads(self._DOCUMENT)

    @pytest.mark.parametrize("document, expected", [("[]", []), ("  [ ] ", []), ('{"error": "x"}', []), ("", [])])
    def test_empty_or_non_array_documents_yield_nothing(self, document: str, expected: list[Any]) -> None:
        assert list(iter_json_array(io.BytesIO(document.encode()), chunk_size=2)) == expected

    @pytest.mark.parametrize("document", ['[{"a": 1}, {"b": 2}', '[{"a": 1}, {"b": '])
    def test_truncated_array_raises(self, document: str) -> None:
        with pytest.raises(ValueError):
            list(iter_json_array(io.BytesIO(document.encode()), chunk_size=3))


class TestBaseUrl:
    def test_invalid_region_raises(self) -> None:
        with pytest.raises(ValueError):
            _base_url("evil")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "script, expected, paths",
        [
            (
                [_token(), _profiles([{"profileId": 1}])],
                (True, None),
                ["/auth/o2/token", "/v2/profiles"],
            ),
            (
                always(ScriptedResponse(status=400)),
                (False, LWA_REJECTED_MESSAGE),
                ["/auth/o2/token"],
            ),
            (
                always(ScriptedResponse(status=503)),
                (False, UNAVAILABLE_MESSAGE),
                ["/auth/o2/token"],
            ),
            (
                [_token(), ScriptedResponse(status=403)],
                (False, PROFILES_DENIED_MESSAGE),
                ["/auth/o2/token", "/v2/profiles"],
            ),
            (
                [_token(), ScriptedResponse(status=401)],
                (False, PROFILES_DENIED_MESSAGE),
                ["/auth/o2/token", "/v2/profiles"],
            ),
            (
                [_token(), *[ScriptedResponse(status=500)] * 10],
                (False, UNAVAILABLE_MESSAGE),
                None,
            ),
            (
                always(requests.ConnectionError()),
                (False, UNAVAILABLE_MESSAGE),
                None,
            ),
        ],
    )
    def test_validate_credentials_outcomes(
        self, script: Script, expected: tuple[bool, str | None], paths: list[str] | None
    ) -> None:
        with scripted_network(script) as network:
            assert validate_credentials("na", "cid", "sec", "rt") == expected
        if paths is not None:
            assert [request.path for request in network.requests_log[: len(paths)]] == paths

    def test_invalid_region_rejected_without_request(self) -> None:
        with scripted_network([]) as network:
            assert validate_credentials("evil", "cid", "sec", "rt") == (False, INVALID_REGION_MESSAGE)
        assert network.requests_log == []

    def test_source_returns_the_credential_check_result(self) -> None:
        config = AmazonAdsSourceConfig(region="na", client_id="cid", client_secret="sec", refresh_token="rt")
        with scripted_network([_token(), ScriptedResponse(status=403)]) as network:
            result = AmazonAdsSource().validate_credentials(config, 123)

        assert result == (False, PROFILES_DENIED_MESSAGE)
        assert network.requests_log[1].origin == "https://advertising-api.amazon.com"
        assert network.requests_log[0].body is not None
        assert b"refresh_token=rt" in network.requests_log[0].body


class TestGetRows:
    @pytest.mark.parametrize(
        "endpoint, id_field",
        [
            ("sp_campaigns", "campaignId"),
            ("sp_ad_groups", "adGroupId"),
            ("sp_product_ads", "adId"),
            ("sp_keywords", "keywordId"),
            ("sp_targets", "targetId"),
        ],
    )
    def test_entity_fan_out_per_profile_with_scope_header(self, endpoint: str, id_field: str) -> None:
        config = AMAZON_ADS_ENDPOINTS[endpoint]
        result = _driver().run(
            endpoint,
            [
                _token(),
                _profiles([{"profileId": 1}]),
                ScriptedResponse(json={config.data_key: [{id_field: 11}], "nextToken": "tok"}),
                ScriptedResponse(json={config.data_key: [{id_field: 12}]}),
            ],
        )
        assert result.raised is None
        assert [(row[id_field], row["_profile_id"]) for row in result.rows] == [(11, "1"), (12, "1")]
        assert result.paths[2:] == [config.path, config.path]
        assert result.requests[2].headers["amazon-advertising-api-scope"] == "1"
        assert result.requests[2].headers["content-type"] == config.media_type
        assert result.requests[2].json() == {"maxResults": PAGE_SIZE}
        assert result.requests[3].json() == {"maxResults": PAGE_SIZE, "nextToken": "tok"}

    @pytest.mark.parametrize(
        "endpoint, expected_body",
        [
            ("sp_campaigns", {"maxResults": PAGE_SIZE}),
            # `/portfolios/list` declares no `maxResults`, and rejects a body field it does not know.
            ("portfolios", {}),
            ("sp_negative_keywords", {"maxResults": PAGE_SIZE}),
            # Sponsored Brands and Sponsored Display share the unified Ads API paths, so the ad
            # product filter is the only thing that keeps one product's rows out of the other's
            # table. Amazon caps `maxResults` at 100 per entity query, and at 5000 for targets.
            ("sb_campaigns", {"maxResults": 100, "adProductFilter": {"include": ["SPONSORED_BRANDS"]}}),
            ("sb_targets", {"maxResults": 5000, "adProductFilter": {"include": ["SPONSORED_BRANDS"]}}),
            ("sd_ads", {"maxResults": 100, "adProductFilter": {"include": ["SPONSORED_DISPLAY"]}}),
            ("sd_targets", {"maxResults": 5000, "adProductFilter": {"include": ["SPONSORED_DISPLAY"]}}),
            # The Sponsored TV lists cap `maxResults` at 100.
            ("st_campaigns", {"maxResults": 100}),
            ("st_targets", {"maxResults": 100}),
        ],
    )
    def test_list_request_body_per_endpoint(self, endpoint: str, expected_body: dict[str, Any]) -> None:
        config = AMAZON_ADS_ENDPOINTS[endpoint]
        result = _driver().run(
            endpoint,
            [
                _token(),
                _profiles([{"profileId": 1}]),
                ScriptedResponse(json={config.data_key: [{"id": 1}], "nextToken": "tok"}),
                ScriptedResponse(json={config.data_key: [{"id": 2}]}),
            ],
        )
        assert result.raised is None
        assert result.requests[2].json() == expected_body
        assert result.requests[3].json() == {**expected_body, "nextToken": "tok"}

    @pytest.mark.parametrize(
        "endpoint, expected_client_id",
        [("sb_campaigns", "cid"), ("sd_campaigns", "cid"), ("sp_campaigns", None)],
    )
    def test_unified_ads_api_sends_its_own_client_id_header(
        self, endpoint: str, expected_client_id: str | None
    ) -> None:
        config = AMAZON_ADS_ENDPOINTS[endpoint]
        result = _driver().run(
            endpoint,
            [_token(), _profiles([{"profileId": 1}]), ScriptedResponse(json={config.data_key: [{"id": 1}]})],
        )
        assert result.raised is None
        assert result.requests[2].headers.get("amazon-ads-clientid") == expected_client_id

    @pytest.mark.parametrize(
        "endpoint, expected_query",
        [
            ("sp_campaigns", {}),
            ("invoices", {"apiProgram": ("billing",), "accessLevel": ("view",)}),
            ("change_history", {"apiProgram": ("campaign",), "accessLevel": ("view",)}),
        ],
    )
    def test_profile_discovery_asks_for_plain_json_and_the_tables_permission(
        self, endpoint: str, expected_query: dict[str, tuple[str, ...]]
    ) -> None:
        result = _driver().run(endpoint, [_token(), _profiles([])])
        assert result.raised is None
        profiles_request = result.requests[1]
        assert profiles_request.path == "/v2/profiles"
        assert profiles_request.query == expected_query
        assert profiles_request.headers.get("accept", "*/*") in ("*/*", "application/json")

    def test_remints_token_on_401(self) -> None:
        result = _driver().run(
            "profiles",
            [_token(), ScriptedResponse(status=401), _token(), _profiles([{"profileId": 1}])],
        )
        assert result.raised is None
        assert result.items == [[{"profileId": 1}]]
        # One mint at start + one re-mint after the 401.
        assert result.paths.count("/auth/o2/token") == 2

    @pytest.mark.parametrize("status_code", [425, 429, 500, 503])
    def test_retryable_statuses_are_retried_then_reraised(self, status_code: int) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            return _token() if request.url == LWA_TOKEN_URL else ScriptedResponse(status=status_code)

        result = _driver().run("profiles", respond)
        assert isinstance(result.raised, AmazonAdsRetryableError)
        assert len(result.requests) > 2
        assert set(result.paths) == {"/auth/o2/token", "/v2/profiles"}

    @pytest.mark.parametrize("region", ["na", "eu", "fe"])
    def test_targets_query_bad_request_is_non_retryable(self, region: Literal["na", "eu", "fe"]) -> None:
        # The unified Ads API rejects `sb_targets`/`sd_targets` (which share this path) with a 400
        # rather than an empty page when the profile has no campaigns of that ad product.
        driver = SourceDriver(
            AmazonAdsSource(),
            AmazonAdsSourceConfig(region=region, client_id="cid", client_secret="sec", refresh_token="rt"),
        )
        result = driver.run(
            "sb_targets",
            [_token(), _profiles([{"profileId": 1}]), ScriptedResponse(status=400)],
        )
        assert isinstance(result.raised, requests.HTTPError)
        assert error_message_matches(str(result.raised), AmazonAdsSource().get_non_retryable_errors())


class TestReportRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Iterator[None]:
        with time_machine.travel(_TODAY, tick=False):
            yield

    @staticmethod
    def _run(
        script: Callable[[RecordedRequest], ScriptedResponse],
        *,
        resume_state: AmazonAdsResumeConfig | None = None,
        **inputs: Any,
    ) -> DriveResult:
        return _driver().run("sp_campaign_reports", script, resume_state=resume_state, **inputs)

    def test_report_is_created_polled_and_downloaded(self) -> None:
        result = self._run(
            _report_script(
                rows=[{"campaignId": 2, "date": "2026-06-29"}, {"campaignId": 1, "date": "2026-06-20"}],
                poll_statuses=["PENDING", "PROCESSING", "COMPLETED"],
            ),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-20",
        )
        assert result.raised is None
        assert [row["date"] for row in result.rows] == ["2026-06-29", "2026-06-20"]
        assert all(row["_profile_id"] == "7" for row in result.rows)
        created = _report_requests(result.requests)
        assert len(created) == 1
        body = created[0].json()
        assert body["startDate"] == "2026-06-20"
        assert body["endDate"] == _TODAY
        assert body["configuration"]["reportTypeId"] == SP_CAMPAIGN_REPORT.report_type_id
        assert body["configuration"]["timeUnit"] == "DAILY"
        assert "date" in body["configuration"]["columns"]
        assert result.saved_states == [
            AmazonAdsResumeConfig(profile_id="7", window_start="2026-06-20", report_id="rep-1")
        ]
        assert result.committed_states == result.saved_states
        assert result.final_state is None

    def test_full_refresh_walks_the_retention_window_in_vendor_sized_chunks(self) -> None:
        result = self._run(_report_script(rows=[]))
        assert result.raised is None
        created = [request.json() for request in _report_requests(result.requests)]
        earliest = dt.date.fromisoformat(_TODAY) - dt.timedelta(days=SP_CAMPAIGN_REPORT.retention_days - 1)
        assert created[0]["startDate"] == earliest.isoformat()
        assert created[-1]["endDate"] == _TODAY
        assert all(
            (dt.date.fromisoformat(body["endDate"]) - dt.date.fromisoformat(body["startDate"])).days
            < SP_CAMPAIGN_REPORT.max_window_days
            for body in created
        )

    def test_resumes_the_pending_report_instead_of_asking_for_a_second(self) -> None:
        result = self._run(
            _report_script(rows=[{"date": "2026-06-25"}]),
            resume_state=AmazonAdsResumeConfig(profile_id="7", window_start="2026-06-20", report_id="rep-in-flight"),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-20",
        )
        assert result.raised is None
        assert _report_requests(result.requests) == []
        polled = [request.url for request in result.requests if request.path.startswith("/reporting/reports/")]
        assert polled and all(url.endswith("rep-in-flight") for url in polled)

    def test_failed_report_reports_amazons_reason(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.url == LWA_TOKEN_URL:
                return _token()
            if request.path == "/v2/profiles":
                return _profiles([{"profileId": 7}])
            if request.method == "POST":
                return ScriptedResponse(json={"reportId": "rep-1"})
            return ScriptedResponse(json={"status": "FAILED", "failureReason": "Date range exceeds retention"})

        result = self._run(
            respond,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-20",
        )
        assert isinstance(result.raised, AmazonAdsReportError)
        assert "Date range exceeds retention" in str(result.raised)

    def test_report_still_generating_after_the_budget_is_retryable(self) -> None:
        result = self._run(
            _report_script(rows=[], poll_statuses=["PROCESSING"]),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-20",
        )
        assert isinstance(result.raised, AmazonAdsRetryableError)
        polls = [path for path in result.paths if path.startswith("/reporting/reports/")]
        assert len(polls) == REPORT_POLL_BUDGET_SECONDS // REPORT_POLL_INTERVAL_SECONDS + 1

    def test_download_url_outside_amazon_is_rejected(self) -> None:
        result = self._run(
            _report_script(rows=[], report_url="https://attacker.example.com/report.json.gz"),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-20",
        )
        assert isinstance(result.raised, ValueError)
        assert "outside Amazon" in str(result.raised)
        assert not any(request.origin == "https://attacker.example.com" for request in result.requests)


class TestBreakdownReportRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Iterator[None]:
        with time_machine.travel(_TODAY, tick=False):
            yield

    @pytest.mark.parametrize(
        "endpoint, report_type_id, ad_product, group_by",
        [
            ("sp_search_term_reports", "spSearchTerm", "SPONSORED_PRODUCTS", ["searchTerm"]),
            ("sp_advertised_product_reports", "spAdvertisedProduct", "SPONSORED_PRODUCTS", ["advertiser"]),
            ("sp_targeting_reports", "spTargeting", "SPONSORED_PRODUCTS", ["targeting"]),
            ("sp_purchased_product_reports", "spPurchasedProduct", "SPONSORED_PRODUCTS", ["asin"]),
            ("sb_purchased_product_reports", "sbPurchasedProduct", "SPONSORED_BRANDS", ["purchasedAsin"]),
        ],
    )
    def test_report_rows_get_a_stable_row_id_from_the_grouping_columns(
        self, endpoint: str, report_type_id: str, ad_product: str, group_by: list[str]
    ) -> None:
        report = AMAZON_ADS_ENDPOINTS[endpoint].report
        assert report is not None
        base: dict[str, Any] = {column: f"{column}-1" for column in report.key_columns}
        # The second row differs only in a metric, the third in one grouping column, and the
        # fourth has a null grouping column.
        first_key = report.key_columns[0]
        rows: list[dict[str, Any]] = [
            {**base, "date": "2026-06-25", "clicks": 1},
            {**base, "date": "2026-06-26", "clicks": 2},
            {**base, first_key: "other", "date": "2026-06-26", "clicks": 3},
            {**base, report.key_columns[-1]: None, "date": "2026-06-26", "clicks": 4},
        ]
        script = _report_script(rows=rows)

        first = _driver().run(
            endpoint, script, should_use_incremental_field=True, db_incremental_field_last_value="2026-06-20"
        )
        second = _driver().run(
            endpoint,
            _report_script(rows=list(reversed(rows))),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-20",
        )

        assert first.raised is None
        body = _report_requests(first.requests)[0].json()["configuration"]
        assert (body["reportTypeId"], body["adProduct"], body["groupBy"]) == (report_type_id, ad_product, group_by)
        by_clicks = {row["clicks"]: row["_row_id"] for row in first.rows}
        assert by_clicks[1] == by_clicks[2]
        assert len({by_clicks[2], by_clicks[3], by_clicks[4]}) == 3
        assert {row["clicks"]: row["_row_id"] for row in second.rows} == by_clicks
        keys = {tuple(row[key] for key in AMAZON_ADS_ENDPOINTS[endpoint].primary_keys) for row in first.rows}
        assert len(keys) == len(rows)


class TestBudgetRuleRows:
    def test_budget_rules_send_the_page_size_on_every_page(self) -> None:
        result = _driver().run(
            "sp_budget_rules",
            [
                _token(),
                _profiles([{"profileId": 1}]),
                ScriptedResponse(json={"budgetRulesForAdvertiserResponse": [{"ruleId": "r1"}], "nextToken": "tok"}),
                ScriptedResponse(json={"budgetRulesForAdvertiserResponse": [{"ruleId": "r2"}]}),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"ruleId": "r1", "_profile_id": "1"}, {"ruleId": "r2", "_profile_id": "1"}]
        first, second = result.requests[2:]
        assert (first.method, first.path, second.method, second.path) == (
            "GET",
            "/sp/budgetRules",
            "GET",
            "/sp/budgetRules",
        )
        assert first.query == {"pageSize": ("30",)}
        assert second.query == {"pageSize": ("30",), "nextToken": ("tok",)}
        assert first.headers["amazon-advertising-api-scope"] == "1"

    def test_rule_campaigns_fan_out_per_profile_and_rule(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.url == LWA_TOKEN_URL:
                return _token()
            if request.path == "/v2/profiles":
                return _profiles([{"profileId": 1}, {"profileId": 2}])
            profile = request.headers["amazon-advertising-api-scope"]
            if request.path == "/sp/budgetRules":
                rules = [{"ruleId": "r/1"}, {"ruleId": "r2"}] if profile == "1" else [{"ruleId": "r3"}]
                return ScriptedResponse(json={"budgetRulesForAdvertiserResponse": rules})
            if request.path == "/sp/budgetRules/r%2F1/campaigns" and "nextToken" not in request.query:
                return ScriptedResponse(json={"associatedCampaigns": [{"campaignId": "c1"}], "nextToken": "tok"})
            if request.path == "/sp/budgetRules/r%2F1/campaigns":
                return ScriptedResponse(json={"associatedCampaigns": [{"campaignId": "c2"}]})
            if request.path == "/sp/budgetRules/r3/campaigns":
                return ScriptedResponse(json={"associatedCampaigns": [{"campaignId": "c1"}]})
            return ScriptedResponse(json={"associatedCampaigns": []})

        result = _driver().run("sp_budget_rule_campaigns", respond)
        assert result.raised is None
        assert [(row["_profile_id"], row["ruleId"], row["campaignId"]) for row in result.rows] == [
            ("1", "r/1", "c1"),
            ("1", "r/1", "c2"),
            ("2", "r3", "c1"),
        ]
        campaign_requests = [request for request in result.requests if request.path.endswith("/campaigns")]
        assert [request.path for request in campaign_requests] == [
            "/sp/budgetRules/r%2F1/campaigns",
            "/sp/budgetRules/r%2F1/campaigns",
            "/sp/budgetRules/r2/campaigns",
            "/sp/budgetRules/r3/campaigns",
        ]
        assert all(request.query["pageSize"] == ("30",) for request in campaign_requests)


class TestAccountAndBillingRows:
    def test_ads_accounts_are_listed_once_without_a_profile_scope(self) -> None:
        config = AMAZON_ADS_ENDPOINTS["ads_accounts"]
        result = _driver().run(
            "ads_accounts",
            [
                _token(),
                ScriptedResponse(json={"adsAccounts": [{"adsAccountId": "a1"}], "nextToken": "tok"}),
                ScriptedResponse(json={"adsAccounts": [{"adsAccountId": "a2"}]}),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"adsAccountId": "a1"}, {"adsAccountId": "a2"}]
        assert result.paths[1:] == ["/adsAccounts/list", "/adsAccounts/list"]
        assert "amazon-advertising-api-scope" not in result.requests[1].headers
        assert result.requests[1].headers["content-type"] == config.media_type
        assert result.requests[1].headers["accept"] == config.media_type
        assert result.requests[1].json() == {"maxResults": 100}
        assert result.requests[2].json() == {"maxResults": 100, "nextToken": "tok"}

    @pytest.mark.parametrize("wrapped", [False, True])
    def test_invoices_page_with_a_query_cursor(self, wrapped: bool) -> None:
        def page(body: dict[str, Any]) -> ScriptedResponse:
            return ScriptedResponse(json={"status": "success", "payload": body} if wrapped else body)

        result = _driver().run(
            "invoices",
            [
                _token(),
                _profiles([{"profileId": 1}]),
                page({"invoiceSummaries": [{"id": "inv-1"}], "nextCursor": "cur"}),
                page({"invoiceSummaries": [{"id": "inv-2"}], "nextCursor": None}),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "inv-1", "_profile_id": "1"}, {"id": "inv-2", "_profile_id": "1"}]
        first, second = result.requests[2:]
        assert (first.method, first.path, second.method, second.path) == ("GET", "/invoices", "GET", "/invoices")
        assert first.query == {"count": ("100",)}
        assert second.query == {"cursor": ("cur",)}
        assert first.headers["amazon-advertising-api-scope"] == "1"
        assert first.headers["accept"] == AMAZON_ADS_ENDPOINTS["invoices"].media_type


class TestChangeHistoryRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Iterator[None]:
        with time_machine.travel(_TODAY, tick=False):
            yield

    @pytest.mark.parametrize(
        "should_use_incremental_field, last_value, expected_from",
        [
            (False, None, _HISTORY_EARLIEST_MS),
            (True, None, _HISTORY_EARLIEST_MS),
            (True, _NOW_MS - 3_600_000, _NOW_MS - 3_600_000 - HISTORY_LOOKBACK_MS),
            (True, str(_NOW_MS - 3_600_000), _NOW_MS - 3_600_000 - HISTORY_LOOKBACK_MS),
            (True, _HISTORY_EARLIEST_MS - 86_400_000, _HISTORY_EARLIEST_MS),
        ],
    )
    def test_history_query_window(
        self, should_use_incremental_field: bool, last_value: Any, expected_from: int
    ) -> None:
        result = _driver().run(
            "change_history",
            [_token(), _profiles([{"profileId": 1}]), ScriptedResponse(json={"events": []})],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
        assert result.raised is None
        request = result.requests[2]
        assert (request.method, request.path) == ("POST", "/history")
        assert request.headers["amazon-advertising-api-scope"] == "1"
        assert request.json() == {
            "count": HISTORY_PAGE_SIZE,
            "eventTypes": {
                event_type: {"parents": [{"useProfileIdAdvertiser": True}]} for event_type in HISTORY_EVENT_TYPES
            },
            "fromDate": expected_from,
            "toDate": _NOW_MS,
            "sort": {"key": "DATE", "direction": "ASC"},
        }

    def test_history_pages_and_keys_events_that_share_a_timestamp(self) -> None:
        shared = {"entityType": "CAMPAIGN", "entityId": "c1", "changeType": "PLACEMENT_GROUP", "timestamp": 5}
        events = [
            {**shared, "newValue": "10", "metadata": {"placementGroupPosition": "TOP_OF_SEARCH"}},
            {**shared, "newValue": "10", "metadata": {"placementGroupPosition": "DETAIL_PAGE"}},
        ]
        script = [
            _token(),
            _profiles([{"profileId": 1}]),
            ScriptedResponse(json={"events": events, "nextToken": "tok"}),
            ScriptedResponse(json={"events": [{**shared, "changeType": "STATUS", "newValue": "PAUSED"}]}),
        ]

        first = _driver().run("change_history", script)
        second = _driver().run("change_history", script)

        assert first.raised is None
        assert len(first.rows) == 3
        assert len({row["_event_id"] for row in first.rows}) == 3
        assert [row["_event_id"] for row in first.rows] == [row["_event_id"] for row in second.rows]
        assert all(row["_profile_id"] == "1" for row in first.rows)
        assert first.requests[3].json() == {**first.requests[2].json(), "nextToken": "tok"}

    def test_history_stages_its_position_and_resumes_from_it(self) -> None:
        event = {"entityType": "AD", "entityId": "a1", "changeType": "STATUS", "timestamp": 5}
        result = _driver().run(
            "change_history",
            [
                _token(),
                _profiles([{"profileId": 1}, {"profileId": 2}, {"profileId": 3}]),
                ScriptedResponse(json={"events": [event], "nextToken": "tok-2"}),
                ScriptedResponse(json={"events": []}),
                ScriptedResponse(json={"events": [event]}),
            ],
            resume_state=AmazonAdsResumeConfig(
                profile_id="2", window_start="1000", history_to_ms=2000, next_token="tok-1"
            ),
        )
        assert result.raised is None
        assert [request.headers["amazon-advertising-api-scope"] for request in result.requests[2:]] == ["2", "2", "3"]
        bodies = [request.json() for request in result.requests[2:]]
        assert [(body["fromDate"], body["toDate"]) for body in bodies] == [(1000, 2000)] * 3
        assert [body.get("nextToken") for body in bodies] == ["tok-1", "tok-2", None]
        assert [row["_profile_id"] for row in result.rows] == ["2", "3"]
        assert result.saved_states == [
            AmazonAdsResumeConfig(profile_id="2", window_start="1000", history_to_ms=2000, next_token="tok-2"),
            AmazonAdsResumeConfig(profile_id="3", window_start="1000", history_to_ms=2000, next_token=None),
        ]
        assert result.final_state is None


class TestAmazonAdsSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = AMAZON_ADS_ENDPOINTS[endpoint]

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.url == LWA_TOKEN_URL:
                return _token()
            return _profiles([]) if request.path == "/v2/profiles" else ScriptedResponse(json={})

        result = _driver().run(endpoint, respond)
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        assert result.response.sort_mode is None
        if config.report is None:
            assert result.response.partition_mode is None
            assert result.response.partition_keys is None
        else:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_format == "day"
            assert result.response.partition_keys == ["date"]
