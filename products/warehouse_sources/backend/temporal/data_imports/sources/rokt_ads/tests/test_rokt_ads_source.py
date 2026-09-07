from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.rokt_ads import (
    RoktAdsError,
    RoktAdsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.settings import (
    ENDPOINTS,
    INCREMENTAL_LOOKBACK_SECONDS,
    PRIMARY_KEYS,
    SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.source import RoktAdsSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.source"


def _input_field(name: str) -> SourceFieldInputConfig:
    field = next(f for f in RoktAdsSource().get_source_config.fields if f.name == name)
    assert isinstance(field, SourceFieldInputConfig)
    return field


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
    def test_source_type(self):
        assert RoktAdsSource().source_type == ExternalDataSourceType.ROKTADS

    def test_connection_host_fields_force_secret_reentry(self):
        # `account_id` picks the account the stored app secret is spent against.
        assert RoktAdsSource().connection_host_fields == ["account_id"]

    def test_config_is_an_advertising_source_with_alpha_release_status(self):
        config = RoktAdsSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ADVERTISING
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_finished_source_is_not_hidden_from_users(self):
        assert not RoktAdsSource().get_source_config.unreleasedSource

    def test_config_collects_the_credentials_the_query_api_needs(self):
        fields = {field.name: field for field in RoktAdsSource().get_source_config.fields}
        assert {"app_id", "app_secret", "account_id"} <= set(fields)
        assert _input_field("app_secret").secret is True
        assert _input_field("app_id").required and _input_field("account_id").required

    def test_optional_report_settings_are_not_required(self):
        assert _input_field("timezone_variation").required is False
        assert _input_field("currency_code").required is False

    def test_api_docs_url_points_at_the_query_api(self):
        assert RoktAdsSource.api_docs_url.startswith("https://")
        assert "query-api" in RoktAdsSource.api_docs_url

    def test_table_catalog_is_published_without_credentials(self):
        assert RoktAdsSource.lists_tables_without_credentials is True


class TestGetSchemas:
    def test_lists_every_declared_table(self):
        names = [schema.name for schema in RoktAdsSource().get_schemas(_config(), team_id=1)]
        assert names == SCHEMA_NAMES

    def test_reports_are_incremental_and_accounts_is_not(self):
        schemas = {s.name: s for s in RoktAdsSource().get_schemas(_config(), team_id=1)}
        assert schemas["Accounts"].supports_incremental is False
        for name in ENDPOINTS:
            assert schemas[name].supports_incremental is True

    def test_reports_carry_the_datetime_cursor(self):
        schemas = {s.name: s for s in RoktAdsSource().get_schemas(_config(), team_id=1)}
        for name in ENDPOINTS:
            assert [f["field"] for f in schemas[name].incremental_fields] == ["datetime"]

    def test_reports_re_read_a_trailing_window_because_rokt_restates_days(self):
        schemas = {s.name: s for s in RoktAdsSource().get_schemas(_config(), team_id=1)}
        for name in ENDPOINTS:
            assert schemas[name].default_incremental_lookback_seconds == INCREMENTAL_LOOKBACK_SECONDS
        assert schemas["Accounts"].default_incremental_lookback_seconds is None

    def test_names_filter_narrows_the_catalog(self):
        schemas = RoktAdsSource().get_schemas(_config(), team_id=1, names=["CreativePerformance"])
        assert [s.name for s in schemas] == ["CreativePerformance"]

    def test_get_schemas_makes_no_network_call(self):
        with patch(f"{SOURCE_MODULE}.RoktAdsClient") as client:
            RoktAdsSource().get_schemas(_config(), team_id=1)
        client.assert_not_called()


class TestValidateCredentials:
    def test_delegates_to_the_transport_validator(self):
        with patch(f"{SOURCE_MODULE}.validate_rokt_credentials", return_value=(True, None)) as validate:
            assert RoktAdsSource().validate_credentials(_config(), team_id=1) == (True, None)
        validate.assert_called_once_with("app-id", "app-secret", "acc_1")

    def test_surfaces_the_failure_message(self):
        with patch(f"{SOURCE_MODULE}.validate_rokt_credentials", return_value=(False, "nope")):
            assert RoktAdsSource().validate_credentials(_config(), team_id=1) == (False, "nope")


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

    def test_accounts_is_not_partitioned(self):
        response = self._response("Accounts")
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_sort_mode_matches_the_ascending_order_the_report_requests(self):
        assert self._response("CampaignPerformance").sort_mode == "asc"

    def test_full_refresh_run_passes_no_cursor(self):
        with patch(f"{SOURCE_MODULE}.RoktAdsClient"), patch(f"{SOURCE_MODULE}.rokt_ads_source") as transport:
            response = RoktAdsSource().source_for_pipeline(
                _config(), MagicMock(), _inputs(should_use_incremental_field=False)
            )
            response.items()
        assert transport.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_incremental_run_passes_the_cursor_through(self):
        with patch(f"{SOURCE_MODULE}.RoktAdsClient"), patch(f"{SOURCE_MODULE}.rokt_ads_source") as transport:
            response = RoktAdsSource().source_for_pipeline(_config(), MagicMock(), _inputs())
            response.items()
        assert transport.call_args.kwargs["db_incremental_field_last_value"] == "2026-08-01"

    def test_blank_optional_settings_are_passed_as_none(self):
        with patch(f"{SOURCE_MODULE}.RoktAdsClient"), patch(f"{SOURCE_MODULE}.rokt_ads_source") as transport:
            response = RoktAdsSource().source_for_pipeline(_config(), MagicMock(), _inputs())
            response.items()
        assert transport.call_args.kwargs["timezone_variation"] is None
        assert transport.call_args.kwargs["currency_code"] is None

    def test_configured_optional_settings_reach_the_transport(self):
        config = _config(timezone_variation="Australia/Sydney", currency_code="AUD")
        with patch(f"{SOURCE_MODULE}.RoktAdsClient"), patch(f"{SOURCE_MODULE}.rokt_ads_source") as transport:
            response = RoktAdsSource().source_for_pipeline(config, MagicMock(), _inputs())
            response.items()
        assert transport.call_args.kwargs["timezone_variation"] == "Australia/Sydney"
        assert transport.call_args.kwargs["currency_code"] == "AUD"


class TestNonRetryableErrors:
    def test_auth_and_permission_failures_stop_retrying(self):
        errors = RoktAdsSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)
        assert any("400" in key for key in errors)

    def test_account_capability_errors_stop_retrying(self):
        errors = RoktAdsSource().get_non_retryable_errors()
        assert "Deselect this table or ask Rokt to enable those dimensions" in errors
        assert "Rokt account grants none of the metrics" in errors

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

    def test_a_token_endpoint_400_is_not_read_as_a_report_error(self):
        # The report 400 key is pinned to the Query API path, so a 400 from the OAuth token endpoint
        # (same host) must not borrow the report copy that tells the user to check the tables and
        # account ID when their credentials are the real fault. Un-pinning the key would re-match it.
        token_error = "400 Client Error: Bad Request for url: https://api.rokt.com/auth/oauth2/token"
        errors = RoktAdsSource().get_non_retryable_errors()
        assert not error_message_matches(token_error, errors.keys())


class TestCanonicalDescriptions:
    def test_every_table_is_documented(self):
        descriptions = RoktAdsSource().get_canonical_descriptions()
        assert set(descriptions) == set(SCHEMA_NAMES)

    def test_report_tables_document_their_key_columns(self):
        descriptions = RoktAdsSource().get_canonical_descriptions()
        for name in ENDPOINTS:
            columns = descriptions[name]["columns"]
            for key in PRIMARY_KEYS[name]:
                assert key in columns, f"{name} primary key column {key} is undocumented"
