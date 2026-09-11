import gzip
import json
import datetime as dt
from typing import Any
from urllib.parse import urlparse

import pytest
import time_machine
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.amazon_ads import (
    LWA_TOKEN_URL,
    PAGE_SIZE,
    REPORT_POLL_MAX_ATTEMPTS,
    AmazonAdsReportError,
    AmazonAdsResumeConfig,
    AmazonAdsRetryableError,
    _base_url,
    amazon_ads_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.settings import (
    AMAZON_ADS_ENDPOINTS,
    ENDPOINTS,
    SP_CAMPAIGN_REPORT,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.amazon_ads"
_REPORT_URL = "https://offline-report-storage.s3.amazonaws.com/report.json.gz"
_TODAY = "2026-06-30"


def _token_response() -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"access_token": "the-token", "expires_in": 3600}
    resp.status_code = 200
    resp.ok = True
    return resp


def _json_response(body: Any) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


def _gzip_response(rows: list[dict[str, Any]]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.content = gzip.compress(json.dumps(rows).encode())
    resp.status_code = 200
    resp.ok = True
    return resp


def _wire_report_session(
    mock_session: mock.MagicMock,
    profiles: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    poll_statuses: list[str] | None = None,
    report_url: str = _REPORT_URL,
) -> list[dict[str, Any]]:
    """Play the create -> poll -> download flow, and hand back the report bodies we sent."""
    created: list[dict[str, Any]] = []
    statuses = list(poll_statuses or ["COMPLETED"])

    def post(url: str, **kwargs: Any) -> mock.MagicMock:
        if url == LWA_TOKEN_URL:
            return _token_response()
        created.append(kwargs["json"])
        return _json_response({"reportId": f"rep-{len(created)}"})

    def get(url: str, **kwargs: Any) -> mock.MagicMock:
        if url.endswith("/v2/profiles"):
            return _json_response(profiles)
        if "/reporting/reports/" in url:
            status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
            return _json_response({"status": status, "url": report_url if status == "COMPLETED" else None})
        return _gzip_response(rows)

    mock_session.return_value.post.side_effect = post
    mock_session.return_value.get.side_effect = get
    return created


def _resume_manager(state: AmazonAdsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = state is not None
    manager.load_state.return_value = state
    return manager


class TestBaseUrl:
    @pytest.mark.parametrize(
        "region, expected_host",
        [
            ("na", "https://advertising-api.amazon.com"),
            ("eu", "https://advertising-api-eu.amazon.com"),
            ("fe", "https://advertising-api-fe.amazon.com"),
        ],
    )
    def test_regional_hosts(self, region, expected_host):
        assert _base_url(region) == expected_host

    def test_invalid_region_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil")


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_when_token_mints_and_profiles_list(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response([{"profileId": 1}])

        assert validate_credentials("na", "cid", "sec", "rt") is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_token_mint_fails(self, mock_session):
        resp = mock.MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("400 Client Error", response=mock.MagicMock())
        mock_session.return_value.post.return_value = resp

        assert validate_credentials("na", "cid", "sec", "rt") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_profiles_forbidden(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        forbidden = mock.MagicMock()
        forbidden.status_code = 403
        mock_session.return_value.get.return_value = forbidden

        assert validate_credentials("na", "cid", "sec", "rt") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_region_rejected_without_request(self, mock_session):
        assert validate_credentials("evil", "cid", "sec", "rt") is False
        mock_session.return_value.post.assert_not_called()


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_profiles_single_fetch(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response([{"profileId": 1}, {"profileId": 2}])

        batches = list(get_rows("na", "cid", "sec", "rt", "profiles", mock.MagicMock()))

        assert batches == [[{"profileId": 1}, {"profileId": 2}]]

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
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_entity_fan_out_per_profile_with_scope_header(self, mock_session, endpoint, id_field):
        config = AMAZON_ADS_ENDPOINTS[endpoint]
        mock_session.return_value.post.side_effect = [
            _token_response(),
            _json_response({config.data_key: [{id_field: 11}], "nextToken": "tok"}),
            _json_response({config.data_key: [{id_field: 12}]}),
        ]
        mock_session.return_value.get.return_value = _json_response([{"profileId": 1}])

        batches = list(get_rows("na", "cid", "sec", "rt", endpoint, mock.MagicMock()))

        flat = [item for batch in batches for item in batch]
        assert [(row[id_field], row["_profile_id"]) for row in flat] == [(11, "1"), (12, "1")]
        first_list_call = mock_session.return_value.post.call_args_list[1]
        assert urlparse(first_list_call.args[0]).path == config.path
        assert first_list_call.kwargs["headers"]["Amazon-Advertising-API-Scope"] == "1"
        assert first_list_call.kwargs["headers"]["Content-Type"] == config.media_type
        assert first_list_call.kwargs["json"] == {"maxResults": PAGE_SIZE}
        second_list_call = mock_session.return_value.post.call_args_list[2]
        assert second_list_call.kwargs["json"] == {"maxResults": PAGE_SIZE, "nextToken": "tok"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_remints_token_on_401(self, mock_session):
        expired = mock.MagicMock()
        expired.status_code = 401
        expired.ok = False
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [expired, _json_response([{"profileId": 1}])]

        batches = list(get_rows("na", "cid", "sec", "rt", "profiles", mock.MagicMock()))

        assert batches == [[{"profileId": 1}]]
        # One mint at start + one re-mint after the 401.
        assert mock_session.return_value.post.call_count == 2

    @pytest.mark.parametrize("status_code", [425, 429, 500, 503])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retryable_statuses_are_retried_then_reraised(self, mock_session, status_code):
        throttled = mock.MagicMock()
        throttled.status_code = status_code
        throttled.ok = False
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = throttled

        with mock.patch(f"{_MODULE}.wait_exponential_jitter", return_value=lambda _state: 0):
            with pytest.raises(AmazonAdsRetryableError):
                list(get_rows("na", "cid", "sec", "rt", "profiles", mock.MagicMock()))

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_no_profiles_yields_nothing(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response([])

        assert list(get_rows("na", "cid", "sec", "rt", "sp_campaigns", mock.MagicMock())) == []


class TestReportRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel(_TODAY, tick=False):
            yield

    def _run(self, manager: mock.MagicMock | None = None, **kwargs: Any) -> list[list[dict[str, Any]]]:
        return list(
            get_rows(
                "na",
                "cid",
                "sec",
                "rt",
                "sp_campaign_reports",
                mock.MagicMock(),
                resumable_source_manager=manager if manager is not None else _resume_manager(),
                **kwargs,
            )
        )

    @mock.patch(f"{_MODULE}.time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_report_is_created_polled_and_downloaded_in_date_order(self, mock_session, _sleep):
        created = _wire_report_session(
            mock_session,
            profiles=[{"profileId": 7}],
            rows=[{"campaignId": 2, "date": "2026-06-29"}, {"campaignId": 1, "date": "2026-06-20"}],
            poll_statuses=["PENDING", "PROCESSING", "COMPLETED"],
        )
        manager = _resume_manager()

        batches = self._run(
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-20",
        )

        assert [row["date"] for batch in batches for row in batch] == ["2026-06-20", "2026-06-29"]
        assert all(row["_profile_id"] == "7" for batch in batches for row in batch)
        assert len(created) == 1
        assert created[0]["startDate"] == "2026-06-20"
        assert created[0]["endDate"] == _TODAY
        assert created[0]["configuration"]["reportTypeId"] == SP_CAMPAIGN_REPORT.report_type_id
        assert created[0]["configuration"]["timeUnit"] == "DAILY"
        assert "date" in created[0]["configuration"]["columns"]
        manager.save_state.assert_called_once_with(
            AmazonAdsResumeConfig(profile_id="7", window_start="2026-06-20", report_id="rep-1")
        )
        manager.clear_state.assert_called_once()

    @mock.patch(f"{_MODULE}.time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_walks_the_retention_window_in_vendor_sized_chunks(self, mock_session, _sleep):
        created = _wire_report_session(mock_session, profiles=[{"profileId": 7}], rows=[])

        self._run()

        earliest = dt.date.fromisoformat(_TODAY) - dt.timedelta(days=SP_CAMPAIGN_REPORT.retention_days - 1)
        assert created[0]["startDate"] == earliest.isoformat()
        assert created[-1]["endDate"] == _TODAY
        assert all(
            (dt.date.fromisoformat(body["endDate"]) - dt.date.fromisoformat(body["startDate"])).days
            < SP_CAMPAIGN_REPORT.max_window_days
            for body in created
        )

    @mock.patch(f"{_MODULE}.time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_the_pending_report_instead_of_asking_for_a_second(self, mock_session, _sleep):
        created = _wire_report_session(mock_session, profiles=[{"profileId": 7}], rows=[{"date": "2026-06-25"}])
        manager = _resume_manager(
            AmazonAdsResumeConfig(profile_id="7", window_start="2026-06-20", report_id="rep-in-flight")
        )

        self._run(manager, should_use_incremental_field=True, db_incremental_field_last_value="2026-06-20")

        assert created == []
        polled = [
            call.args[0]
            for call in mock_session.return_value.get.call_args_list
            if "/reporting/reports/" in call.args[0]
        ]
        assert polled and all(url.endswith("rep-in-flight") for url in polled)

    @mock.patch(f"{_MODULE}.time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_failed_report_reports_amazons_reason(self, mock_session, _sleep):
        def get(url: str, **kwargs: Any) -> mock.MagicMock:
            if url.endswith("/v2/profiles"):
                return _json_response([{"profileId": 7}])
            return _json_response({"status": "FAILED", "failureReason": "Date range exceeds retention"})

        mock_session.return_value.post.side_effect = lambda url, **kwargs: (
            _token_response() if url == LWA_TOKEN_URL else _json_response({"reportId": "rep-1"})
        )
        mock_session.return_value.get.side_effect = get

        with pytest.raises(AmazonAdsReportError, match="Date range exceeds retention"):
            self._run(should_use_incremental_field=True, db_incremental_field_last_value="2026-06-20")

    @mock.patch(f"{_MODULE}.time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_report_still_generating_after_the_budget_is_retryable(self, mock_session, _sleep):
        _wire_report_session(mock_session, profiles=[{"profileId": 7}], rows=[], poll_statuses=["PROCESSING"])

        with pytest.raises(AmazonAdsRetryableError):
            self._run(should_use_incremental_field=True, db_incremental_field_last_value="2026-06-20")

        assert _sleep.call_count == REPORT_POLL_MAX_ATTEMPTS

    @mock.patch(f"{_MODULE}.time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_download_url_outside_amazon_is_rejected(self, mock_session, _sleep):
        _wire_report_session(
            mock_session,
            profiles=[{"profileId": 7}],
            rows=[],
            report_url="https://attacker.example.com/report.json.gz",
        )

        with pytest.raises(ValueError, match="outside Amazon"):
            self._run(should_use_incremental_field=True, db_incremental_field_last_value="2026-06-20")


class TestAmazonAdsSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = AMAZON_ADS_ENDPOINTS[endpoint]
        response = amazon_ads_source("na", "cid", "sec", "rt", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.report is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "day"
            assert response.partition_keys == ["date"]
