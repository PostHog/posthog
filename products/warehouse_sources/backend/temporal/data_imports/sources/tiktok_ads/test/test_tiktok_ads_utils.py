"""Tests for TikTok Ads utility functions."""

import json
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

from django.test import override_settings

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.settings import (
    TIKTOK_ADS_CONFIG,
    EndpointType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.utils import (
    TikTokAdsAPIError,
    TikTokAdsPaginator,
    TikTokDateRangeManager,
    TikTokReportResource,
    list_advertisers,
)


class TestFlattenFunctions:
    """Test suite for TikTok report flattening functions."""

    def test_flatten_tiktok_report_record_non_dict_input(self):
        # Test inputs that cause TypeError (int, None)
        error_inputs: list[object] = [123, None]
        for input_value in error_inputs:
            with pytest.raises(TypeError):
                TikTokReportResource.transform_analytics_reports([cast(dict[str, Any], input_value)])

        # Test inputs that don't cause TypeError (str, list) - they get included as-is
        non_error_inputs: list[object] = ["string_input", ["list", "input"]]
        for input_value in non_error_inputs:
            result = TikTokReportResource.transform_analytics_reports([cast(dict[str, Any], input_value)])
            assert result == [input_value]


class TestSecondaryGoalNormalization:
    """Test suite for secondary goal field normalization."""

    def test_normalize_secondary_goal_fields_mixed_values(self):
        report = {
            "campaign_id": "123",
            "secondary_goal_result": "-",
            "cost_per_secondary_goal_result": "2.5",  # Valid value
            "secondary_goal_result_rate": "-",
            "clicks": "100",
        }

        TikTokReportResource._normalize_secondary_goal_fields(report)

        # Verify the transformation results
        expected_report = {
            "campaign_id": "123",
            "secondary_goal_result": None,  # Converted from "-"
            "cost_per_secondary_goal_result": "2.5",  # Unchanged
            "secondary_goal_result_rate": None,  # Converted from "-"
            "clicks": "100",
        }

        assert report == expected_report


class TestEntityNormalization:
    """Test suite for entity report normalization methods."""

    def test_normalize_timestamps_without_modify_time(self):
        report = {
            "campaign_id": "123",
            "create_time": "2023-09-01 10:00:00",
        }

        TikTokReportResource._normalize_timestamps(report)

        assert report["modify_time"] == "2023-09-01 10:00:00"  # Should use create_time

    def test_convert_comment_settings_disabled(self):
        """Test comment settings conversion when comments are disabled (is_comment_disable = 1)."""
        report = {
            "ad_id": "123",
            "is_comment_disable": 1,
        }

        TikTokReportResource._convert_comment_settings(report)

        assert report["is_comment_disable"] is False  # 1 means enabled, so False


class TestStreamTransformations:
    """Test suite for stream transformations routing."""

    def test_apply_stream_transformations_account_endpoint(self):
        reports = [
            {
                "advertiser_id": "123456",
                "create_time": 1694678400,
            }
        ]

        result = TikTokReportResource.apply_stream_transformations(EndpointType.ACCOUNT, reports)

        assert len(result) == 1
        assert result[0]["advertiser_id"] == "123456"
        assert isinstance(result[0]["create_time"], datetime)

    def test_apply_stream_transformations_asset_endpoint(self):
        # Creative assets have no operational status. Routing them through the entity
        # transformation would invent a `current_status` column TikTok never returned.
        reports = [{"video_id": "v1", "create_time": "2026-01-01 00:00:00"}]

        result = TikTokReportResource.apply_stream_transformations(EndpointType.ASSET, reports)

        assert result == reports

    def test_apply_stream_transformations_unknown_endpoint(self):
        reports = [{"data": "test"}]

        # Create a mock EndpointType enum value that's not handled
        class MockEndpointType(str, Enum):
            UNKNOWN = "unknown"

        mock_endpoint = MockEndpointType.UNKNOWN

        # Use type: ignore to bypass mypy check for this test case
        with pytest.raises(ValueError, match="Endpoint type: .* is not implemented"):
            TikTokReportResource.apply_stream_transformations(mock_endpoint, reports)  # type: ignore[arg-type]


class TestDateRangeFunctions:
    """Test suite for date range calculation functions."""

    @parameterized.expand(
        [
            ("no_incremental_no_last_value", False, None, 365),  # Uses MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS (3 years)
            ("no_incremental_with_last_value", False, datetime.now() - timedelta(days=5), 365),
            ("incremental_no_last_value", True, None, 365),
            ("incremental_with_recent_datetime", True, datetime.now() - timedelta(days=2), 7),
            ("incremental_with_old_datetime", True, datetime.now() - timedelta(days=60), 60),
            ("incremental_with_recent_date", True, date.today() - timedelta(days=3), 7),
            (
                "incremental_with_date_string",
                True,
                (datetime.now() - timedelta(days=12)).strftime("%Y-%m-%d"),
                12,
            ),  # 12 days ago
            ("incremental_with_iso_string", True, (datetime.now() - timedelta(days=4)).isoformat(), 7),
        ]
    )
    def test_get_incremental_date_range_scenarios(self, name, should_use_incremental, last_value, expected_max_days):
        start_date, end_date = TikTokDateRangeManager.get_incremental_range(should_use_incremental, last_value)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        assert end_dt.date() in [today, yesterday]

        days_diff = (end_dt - start_dt).days
        assert days_diff <= expected_max_days + 1

    @parameterized.expand(
        [
            (
                "single_chunk_short_range",
                (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d"),
                (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d"),
                30,
                1,
            ),
            (
                "single_chunk_exact_boundary",
                (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                1,
            ),
            (
                "two_chunks",
                (datetime.now() - timedelta(days=59)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                2,
            ),
            (
                "three_chunks",
                (datetime.now() - timedelta(days=89)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                3,
            ),
            (
                "small_chunk_size",
                (datetime.now() - timedelta(days=13)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                7,
                2,
            ),
            (
                "exact_30_days",
                (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                1,
            ),
            ("same_day", datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%Y-%m-%d"), 30, 1),
        ]
    )
    def test_generate_date_chunks_scenarios(self, name, start_date, end_date, chunk_days, expected_chunks):
        chunks = TikTokDateRangeManager.generate_chunks(start_date, end_date, chunk_days)

        assert len(chunks) == expected_chunks

        first_chunk_start = chunks[0][0]
        last_chunk_end = chunks[-1][1]
        assert first_chunk_start == start_date
        assert last_chunk_end == end_date

        for i, (chunk_start, chunk_end) in enumerate(chunks):
            chunk_start_dt = datetime.strptime(chunk_start, "%Y-%m-%d")
            chunk_end_dt = datetime.strptime(chunk_end, "%Y-%m-%d")

            assert (chunk_end_dt - chunk_start_dt).days <= chunk_days

            if i < len(chunks) - 1:
                next_chunk_start = datetime.strptime(chunks[i + 1][0], "%Y-%m-%d")
                assert (next_chunk_start - chunk_end_dt).days == 1

    def test_generate_date_chunks_invalid_date_format(self):
        valid_end_date = datetime.now().strftime("%Y-%m-%d")
        with pytest.raises(ValueError):
            TikTokDateRangeManager.generate_chunks("invalid-date", valid_end_date, 30)


class TestTikTokAdsPaginator:
    """Test suite for TikTokAdsPaginator class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.paginator = TikTokAdsPaginator()

    def _create_mock_response(self, response_data: dict[Any, Any]) -> Mock:
        """Create a mock Response object with the given JSON data."""
        mock_response = Mock()
        mock_response.json.return_value = {"code": 0, **response_data}
        return mock_response

    def test_update_state_exception_handling(self):
        malformed_responses = [
            {"data": "not_a_dict"},
            {"data": {"page_info": "not_a_dict"}},
        ]

        for response_data in malformed_responses:
            mock_response = self._create_mock_response(cast(dict[Any, Any], response_data))
            with pytest.raises(TikTokAdsAPIError, match="Failed to parse TikTok API response"):
                self.paginator.update_state(mock_response)

        # Test with response that raises exception on json()
        mock_response = Mock()
        mock_response.json.side_effect = Exception("JSON decode error")
        with pytest.raises(TikTokAdsAPIError, match="Failed to parse TikTok API response"):
            self.paginator.update_state(mock_response)

    def test_init_request_sets_current_page(self):
        """init_request must seed the request with the paginator's current page
        so resumed runs target the saved page on their first call."""
        mock_request = Mock()
        mock_request.params = None

        self.paginator.init_request(mock_request)

        assert mock_request.params == {"page": 1}

    def test_get_resume_state_when_no_next_page(self):
        """Freshly constructed paginator has no next page and returns None."""
        assert self.paginator.get_resume_state() is None

    @parameterized.expand(
        [
            ("qps_limit_error", 40100, "App reaches the QPS limit 20", True),
            ("rate_limit_error", 40001, "Rate limit exceeded", False),  # Auth error - not retryable
            ("validation_error", 40002, "Invalid parameter", False),  # Client error - not retryable
            ("server_error", 50000, "Internal server error", True),
            ("internal_service_timeout", 51001, "internal service timeout", True),  # Transient - retryable
            ("internal_service_timeout_51039", 51039, "internal service timeout", True),  # Transient - retryable
        ]
    )
    def test_update_state_api_error_codes(self, name, api_code, message, should_be_retryable):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": api_code,
            "message": message,
            "data": {},
            "request_id": "test-request-id",
        }

        if should_be_retryable:
            with pytest.raises(TikTokAdsAPIError) as exc_info:
                self.paginator.update_state(mock_response)

            assert str(api_code) in str(exc_info.value)
            assert message in str(exc_info.value)
            assert exc_info.value.api_code == api_code
        else:
            with pytest.raises(ValueError) as value_exc_info:
                self.paginator.update_state(mock_response)

            assert "non-retryable" in str(value_exc_info.value)
            assert str(api_code) in str(value_exc_info.value)


class TestHelperFunctions:
    """Test suite for utility helper functions."""

    @parameterized.expand(
        [
            ("campaign_report", EndpointType.REPORT),
            ("ad_group_report", EndpointType.REPORT),
            ("ad_report", EndpointType.REPORT),
            ("campaigns", EndpointType.ENTITY),
            ("ad_groups", EndpointType.ENTITY),
            ("ads", EndpointType.ENTITY),
            ("campaign_demographic_report", EndpointType.REPORT),
            ("ad_group_country_report", EndpointType.REPORT),
            ("ad_platform_report", EndpointType.REPORT),
            ("creative_videos", EndpointType.ASSET),
            ("creative_images", EndpointType.ASSET),
        ]
    )
    def test_is_report_endpoint(self, endpoint_name, expected_endpoint_type):
        config = TIKTOK_ADS_CONFIG.get(endpoint_name)
        assert config is not None, f"Endpoint {endpoint_name} not found in config"
        assert config.endpoint_type == expected_endpoint_type


# Metrics TikTok only accepts on a BASIC report. Requesting any of them alongside an
# audience dimension is rejected outright, which would take the whole breakdown table down.
_BASIC_ONLY_METRICS = {
    "app_promotion_type",
    "billing_event",
    "campaign_budget",
    "campaign_dedicate_type",
    "currency",
    "gross_impressions",
    "split_test",
}

AUDIENCE_REPORT_ENDPOINTS = [
    ("campaign_demographic_report", ["campaign_id", "stat_time_day", "gender", "age"], "AUCTION_CAMPAIGN"),
    ("campaign_country_report", ["campaign_id", "stat_time_day", "country_code"], "AUCTION_CAMPAIGN"),
    ("campaign_platform_report", ["campaign_id", "stat_time_day", "platform"], "AUCTION_CAMPAIGN"),
    ("ad_group_demographic_report", ["adgroup_id", "stat_time_day", "gender", "age"], "AUCTION_ADGROUP"),
    ("ad_group_country_report", ["adgroup_id", "stat_time_day", "country_code"], "AUCTION_ADGROUP"),
    ("ad_group_platform_report", ["adgroup_id", "stat_time_day", "platform"], "AUCTION_ADGROUP"),
    ("ad_demographic_report", ["ad_id", "stat_time_day", "gender", "age"], "AUCTION_AD"),
    ("ad_country_report", ["ad_id", "stat_time_day", "country_code"], "AUCTION_AD"),
    ("ad_platform_report", ["ad_id", "stat_time_day", "platform"], "AUCTION_AD"),
]


def _endpoint_params(endpoint_name: str) -> dict[str, Any]:
    endpoint = cast(dict[str, Any], TIKTOK_ADS_CONFIG[endpoint_name].resource["endpoint"])
    return cast(dict[str, Any], endpoint["params"])


class TestAudienceReportEndpoints:
    @parameterized.expand(AUDIENCE_REPORT_ENDPOINTS)
    def test_breakdown_dimensions_are_part_of_the_primary_key(self, endpoint_name, dimensions, data_level):
        # TikTok returns one row per (entity, day, breakdown value). Dropping a breakdown
        # from the key would collapse every value of it onto one row and make each merge
        # multi-match, so the key has to carry the full dimension list.
        params = _endpoint_params(endpoint_name)

        assert TIKTOK_ADS_CONFIG[endpoint_name].resource["primary_key"] == dimensions
        assert json.loads(params["dimensions"]) == dimensions
        assert params["data_level"] == data_level

    @parameterized.expand(AUDIENCE_REPORT_ENDPOINTS)
    def test_requests_the_audience_report_with_audience_safe_metrics(self, endpoint_name, dimensions, data_level):
        # Reusing the BASIC metric list here is the easy mistake, and TikTok rejects the
        # whole request rather than dropping the unsupported metrics.
        params = _endpoint_params(endpoint_name)
        metrics = set(json.loads(params["metrics"]))

        assert params["report_type"] == "AUDIENCE"
        assert metrics & _BASIC_ONLY_METRICS == set()
        assert metrics & set(dimensions) == set()


class TestListAdvertisers:
    _MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.utils"

    @staticmethod
    def _session_returning(body: dict) -> Mock:
        response = Mock()
        response.json.return_value = body
        session = Mock()
        session.get.return_value = response
        return session

    @override_settings(TIKTOK_ADS_CLIENT_ID="app", TIKTOK_ADS_CLIENT_SECRET="secret")
    def test_returns_advertiser_list_on_success(self):
        session = self._session_returning(
            {"code": 0, "data": {"list": [{"advertiser_id": "1", "advertiser_name": "Acme"}]}}
        )
        with patch(f"{self._MODULE}.make_tracked_session", return_value=session):
            result = list_advertisers("token")

        assert result == [{"advertiser_id": "1", "advertiser_name": "Acme"}]
        # app_id + secret go as query params alongside the user's Access-Token header
        assert session.get.call_args.kwargs["params"] == {"app_id": "app", "secret": "secret"}
        # A timeout must be set — this call runs in the oauth_accounts web worker and a hung
        # TikTok connection would otherwise pin the worker indefinitely.
        assert session.get.call_args.kwargs["timeout"] == 10

    @override_settings(TIKTOK_ADS_CLIENT_ID="app", TIKTOK_ADS_CLIENT_SECRET="secret")
    def test_non_zero_code_raises_with_api_code(self):
        session = self._session_returning({"code": 40105, "message": "Access token is invalid"})
        with patch(f"{self._MODULE}.make_tracked_session", return_value=session):
            with pytest.raises(TikTokAdsAPIError) as excinfo:
                list_advertisers("token")

        assert excinfo.value.api_code == 40105

    @override_settings(TIKTOK_ADS_CLIENT_ID="app", TIKTOK_ADS_CLIENT_SECRET="secret")
    def test_body_without_code_raises_with_none_api_code(self):
        # A malformed body must not be mistaken for one of the known code sets.
        session = self._session_returning({"unexpected": "shape"})
        with patch(f"{self._MODULE}.make_tracked_session", return_value=session):
            with pytest.raises(TikTokAdsAPIError) as excinfo:
                list_advertisers("token")

        assert excinfo.value.api_code is None

    @override_settings(TIKTOK_ADS_CLIENT_ID="app", TIKTOK_ADS_CLIENT_SECRET="secret")
    def test_non_json_body_raises_tiktok_error_not_json_decode_error(self):
        # A proxy answering HTML would otherwise surface as an opaque JSONDecodeError.
        response = Mock()
        response.json.side_effect = ValueError("Expecting value")
        session = Mock()
        session.get.return_value = response
        with patch(f"{self._MODULE}.make_tracked_session", return_value=session):
            with pytest.raises(TikTokAdsAPIError):
                list_advertisers("token")

    @override_settings(TIKTOK_ADS_CLIENT_ID="app", TIKTOK_ADS_CLIENT_SECRET="secret")
    def test_http_error_status_is_raised(self):
        response = Mock()
        response.raise_for_status.side_effect = HTTPError("502 Bad Gateway", response=response)
        session = Mock()
        session.get.return_value = response
        with patch(f"{self._MODULE}.make_tracked_session", return_value=session):
            with pytest.raises(HTTPError):
                list_advertisers("token")
