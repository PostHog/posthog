import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hitpay import HitpaySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.hitpay import HitpayResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.source import HitpaySource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_INCREMENTAL_ENDPOINTS = {"Charges"}
_FULL_REFRESH_ENDPOINTS = {"PaymentRequests", "SubscriptionPlans", "Customers", "RecurringBilling"}


class TestHitpaySource:
    def setup_method(self) -> None:
        self.source = HitpaySource()
        self.team_id = 123
        self.config = HitpaySourceConfig(api_key="key", environment="production")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.HITPAY

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Hitpay"
        assert config.label == "HitPay"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/hitpay.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/hitpay"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key", "platform_api_key", "environment"]

    def test_api_key_field_is_secret_password_and_required(self) -> None:
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_platform_api_key_field_is_secret_but_optional(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "platform_api_key")
        assert field.secret is True
        assert field.required is False

    def test_environment_field_defaults_to_production(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "environment")
        assert field.defaultValue == "production"
        assert {o.value for o in field.options} == {"production", "sandbox"}

    def test_lists_tables_without_credentials_publishes_catalog(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(ENDPOINTS)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["created_at"]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Charges"])
        assert len(schemas) == 1
        assert schemas[0].name == "Charges"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @parameterized.expand(
        [
            ("401", "401 Client Error: Unauthorized for url: https://api.hit-pay.com/v1/charges"),
            ("403", "403 Client Error: Forbidden for url: https://api.hit-pay.com/v1/charges"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.hit-pay.com/v1/charges"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.hit-pay.com/v1/charges"),
            ("timeout", "HTTPSConnectionPool(host='api.hit-pay.com', port=443): Read timed out."),
        ]
    )
    def test_non_retryable_errors_do_not_match_transient(self, _name: str, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is HitpayResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.source.hitpay_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_hitpay_source: mock.MagicMock) -> None:
        config = HitpaySourceConfig(api_key="key", platform_api_key="platform-key", environment="sandbox")
        inputs = mock.MagicMock()
        inputs.schema_name = "Charges"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(config, manager, inputs)

        mock_hitpay_source.assert_called_once()
        kwargs = mock_hitpay_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["platform_api_key"] == "platform-key"
        assert kwargs["environment"] == "sandbox"
        assert kwargs["endpoint"] == "Charges"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.source.hitpay_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_hitpay_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "PaymentRequests"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_hitpay_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.source.hitpay_source")
    def test_source_for_pipeline_blank_platform_key_becomes_none(self, mock_hitpay_source: mock.MagicMock) -> None:
        config = HitpaySourceConfig(api_key="key", platform_api_key="", environment="production")
        inputs = mock.MagicMock()
        inputs.schema_name = "Customers"
        inputs.should_use_incremental_field = False

        self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        assert mock_hitpay_source.call_args.kwargs["platform_api_key"] is None

    @pytest.mark.parametrize(
        ("probe_result", "expected_valid", "expected_message"),
        [
            ((True, None), True, None),
            (
                (False, "Invalid HitPay API key. Check the key in your HitPay dashboard and try again."),
                False,
                "Invalid HitPay API key",
            ),
            ((False, "Could not connect to HitPay with the provided API key."), False, "Could not connect to HitPay"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.source.validate_hitpay_credentials"
    )
    def test_validate_credentials_delegates_and_maps_result(
        self, mock_validate, probe_result, expected_valid, expected_message
    ) -> None:
        mock_validate.return_value = probe_result

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        mock_validate.assert_called_once_with("key", None, "production")
        assert is_valid is expected_valid
        if expected_message is None:
            assert message is None
        else:
            assert expected_message in (message or "")
