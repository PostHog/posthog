import gzip
import json
import datetime as dt
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import time_machine

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.amazon_ads import (
    INVALID_REGION_MESSAGE,
    LWA_REJECTED_MESSAGE,
    LWA_TOKEN_URL,
    PROFILES_DENIED_MESSAGE,
    REPORT_POLL_MAX_ATTEMPTS,
    UNAVAILABLE_MESSAGE,
    AmazonAdsReportError,
    AmazonAdsResumeConfig,
    AmazonAdsRetryableError,
    _base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.settings import (
    AMAZON_ADS_ENDPOINTS,
    ENDPOINTS,
    PAGE_SIZE,
    SP_CAMPAIGN_REPORT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.source import AmazonAdsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazonads import (
    AmazonAdsSourceConfig,
)

_REPORT_URL = "https://offline-report-storage.s3.amazonaws.com/report.json.gz"
_TODAY = "2026-06-30"


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

    def test_report_is_created_polled_and_downloaded_in_date_order(self) -> None:
        result = self._run(
            _report_script(
                rows=[{"campaignId": 2, "date": "2026-06-29"}, {"campaignId": 1, "date": "2026-06-20"}],
                poll_statuses=["PENDING", "PROCESSING", "COMPLETED"],
            ),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-20",
        )
        assert result.raised is None
        assert [row["date"] for row in result.rows] == ["2026-06-20", "2026-06-29"]
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
        assert len(polls) == REPORT_POLL_MAX_ATTEMPTS

    def test_download_url_outside_amazon_is_rejected(self) -> None:
        result = self._run(
            _report_script(rows=[], report_url="https://attacker.example.com/report.json.gz"),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-20",
        )
        assert isinstance(result.raised, ValueError)
        assert "outside Amazon" in str(result.raised)
        assert not any(request.origin == "https://attacker.example.com" for request in result.requests)


class TestAmazonAdsSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = AMAZON_ADS_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_token(), _profiles([])])
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
