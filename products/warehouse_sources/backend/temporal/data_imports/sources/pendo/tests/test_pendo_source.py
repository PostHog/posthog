import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PendoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.pendo import PendoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.source import PendoSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPendoSource:
    def setup_method(self):
        self.source = PendoSource()
        self.team_id = 123
        self.config = PendoSourceConfig(integration_key="integration-key", region="eu")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PENDO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Pendo"
        assert config.label == "Pendo"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/pendo.png"

        input_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert input_names == ["integration_key"]

        select_names = [f.name for f in config.fields if isinstance(f, SourceFieldSelectConfig)]
        assert select_names == ["region"]

    def test_integration_key_field_is_secret_password(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "integration_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_region_field_offers_every_data_region(self):
        config = self.source.get_source_config
        region = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "region")

        assert {option.value for option in region.options} == {"us", "us1", "eu", "jp", "au"}
        assert region.defaultValue == "us"
        assert region.required is True

    def test_get_schemas_are_all_full_refresh(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(schema.supports_incremental is False for schema in schemas)
        assert all(schema.supports_append is False for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["visitors"])
        assert len(schemas) == 1
        assert schemas[0].name == "visitors"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://app.pendo.io/api/v1/page",
            "403 Client Error: Forbidden for url: https://app.pendo.io/api/v1/aggregation",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://app.pendo.io/api/v1/page",
            "500 Server Error for url: https://app.pendo.io/api/v1/aggregation",
        ],
    )
    def test_non_retryable_errors_do_not_match_retryable(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "validate_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            (
                (False, "Invalid Pendo integration key, or the key is missing the required permissions."),
                False,
                "Invalid Pendo integration key, or the key is missing the required permissions.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pendo.source.validate_pendo_credentials"
    )
    def test_validate_credentials(self, mock_validate, validate_return, expected_valid, expected_message):
        mock_validate.return_value = validate_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.integration_key, self.config.region)

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PendoResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pendo.source.pendo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_pendo_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "visitors"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_pendo_source.assert_called_once()
        kwargs = mock_pendo_source.call_args.kwargs
        assert kwargs["integration_key"] == "integration-key"
        assert kwargs["region"] == "eu"
        assert kwargs["endpoint"] == "visitors"
        assert kwargs["resumable_source_manager"] is manager
