from datetime import date

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.rokt_ads import (
    DateWindow,
    ReportCapabilities,
    RoktAdsError,
    RoktAdsResumeConfig,
    build_report_body,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.settings import (
    CAMPAIGN_METRICS,
    ENDPOINTS,
    PRIMARY_KEYS,
    SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.source import RoktAdsSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.source"

ALL_DIMENSIONS = {dimension for endpoint in ENDPOINTS.values() for dimension in endpoint["dimensions"]}
ALL_METRICS = set(CAMPAIGN_METRICS)
MARCH_WINDOW = DateWindow(start=date(2026, 3, 1), end=date(2026, 4, 1))


def _config(**overrides):
    config = MagicMock()
    config.app_id = overrides.get("app_id", "app-id")
    config.app_secret = overrides.get("app_secret", "app-secret")
    config.account_id = overrides.get("account_id", "acc_1")
    config.timezone_variation = overrides.get("timezone_variation", "")
    config.currency_code = overrides.get("currency_code", "")
    return config


def _inputs(schema_name: str = "CampaignPerformance", **overrides):
    inputs = MagicMock()
    inputs.schema_name = schema_name
    inputs.team_id = 1
    inputs.job_id = "job-1"
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", True)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", "2026-08-01")
    return inputs


class TestSourceIdentity:
    def test_connection_host_fields_force_secret_reentry(self):
        # `account_id` picks the account the stored app secret is spent against.
        assert RoktAdsSource().connection_host_fields == ["account_id"]

    def test_api_docs_url_points_at_the_query_api(self):
        assert RoktAdsSource.api_docs_url.startswith("https://")
        assert "query-api" in RoktAdsSource.api_docs_url

    def test_table_catalog_is_published_without_credentials(self):
        assert RoktAdsSource.lists_tables_without_credentials is True


class TestValidateCredentials:
    def test_delegates_to_the_transport_validator(self):
        with patch(f"{SOURCE_MODULE}.validate_rokt_credentials", return_value=(True, None)) as validate:
            assert RoktAdsSource().validate_credentials(_config(), team_id=1) == (True, None)
        validate.assert_called_once_with("app-id", "app-secret", "acc_1")


class TestResumableWiring:
    def test_manager_is_bound_to_the_resume_dataclass(self):
        manager = RoktAdsSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RoktAdsResumeConfig


class TestSourceForPipeline:
    def _response(self, schema_name: str, **input_overrides):
        with patch(f"{SOURCE_MODULE}.RoktAdsClient"):
            return RoktAdsSource().source_for_pipeline(_config(), MagicMock(), _inputs(schema_name, **input_overrides))

    @parameterized.expand(SCHEMA_NAMES)
    def test_every_table_declares_its_primary_key(self, schema_name: str):
        response = self._response(schema_name)
        assert response.name == schema_name
        assert response.primary_keys == PRIMARY_KEYS[schema_name]

    @parameterized.expand(list(ENDPOINTS))
    def test_report_primary_keys_include_the_day_and_every_grain_dimension(self, schema_name: str):
        primary_key = set(PRIMARY_KEYS[schema_name])
        assert "datetime" in primary_key
        # Anything that splits rows must be in the key, or two rows collapse onto one.
        grain = set(ENDPOINTS[schema_name]["dimensions"]) - {"campaign_name", "creative_name", "campaign_objective"}
        assert grain <= primary_key

    @parameterized.expand(list(ENDPOINTS))
    def test_reports_partition_by_the_stable_report_day(self, schema_name: str):
        response = self._response(schema_name)
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["datetime"]

    def test_full_refresh_run_passes_no_cursor(self):
        with patch(f"{SOURCE_MODULE}.RoktAdsClient"), patch(f"{SOURCE_MODULE}.rokt_ads_source") as transport:
            response = RoktAdsSource().source_for_pipeline(
                _config(), MagicMock(), _inputs(should_use_incremental_field=False)
            )
            response.items()
        assert transport.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_blank_optional_settings_are_passed_as_none(self):
        with patch(f"{SOURCE_MODULE}.RoktAdsClient"), patch(f"{SOURCE_MODULE}.rokt_ads_source") as transport:
            response = RoktAdsSource().source_for_pipeline(_config(), MagicMock(), _inputs())
            response.items()
        assert transport.call_args.kwargs["timezone_variation"] is None
        assert transport.call_args.kwargs["currency_code"] is None


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("400 Client Error: Bad Request for url", "endDate cannot be in the future"),
            ("404 Client Error: Not Found for url", "account not found"),
        ]
    )
    def test_a_permanent_http_error_stops_the_retry_storm(self, status_line: str, reason: str):
        # A report request Rokt rejects permanently (a bad request, or a gone account/resource) is a
        # config problem, not a transient failure, so the pipeline must classify the RoktAdsError as
        # non-retryable. The client wraps the HTTPError but keeps the status line in the message, so
        # this guards that the map keys still match it. Without the 404 key the sync would retry a
        # missing account until its budget is spent.
        raised = RoktAdsError(f"{status_line}: https://api.rokt.com/v1/query/accounts/acc_1/campaigns/ — {reason}")
        errors = RoktAdsSource().get_non_retryable_errors()
        assert error_message_matches(str(raised), errors.keys())

    @parameterized.expand(
        [
            # An advertiser-only account holds every metric but lacks the partner dimensions
            # TransactionPerformance needs to identify a row.
            (
                "missing_dimensions",
                ReportCapabilities(
                    dimensions=ALL_DIMENSIONS - {"partner_vertical", "partner_sub_vertical"},
                    metrics=ALL_METRICS,
                ),
            ),
            # An account holds every dimension but is granted none of the table's metrics.
            ("missing_metrics", ReportCapabilities(dimensions=ALL_DIMENSIONS, metrics=set())),
        ]
    )
    def test_capability_config_error_stops_retrying(self, _name, capabilities):
        # build_report_body raises on purpose when a fixed account capability is missing. The
        # non-retryable map must match that raised message, or Temporal retries a dead condition
        # until it exhausts the budget.
        with pytest.raises(RoktAdsError) as raised:
            build_report_body("TransactionPerformance", MARCH_WINDOW, capabilities, None, None)

        errors = RoktAdsSource().get_non_retryable_errors()
        assert error_message_matches(str(raised.value), errors.keys())
