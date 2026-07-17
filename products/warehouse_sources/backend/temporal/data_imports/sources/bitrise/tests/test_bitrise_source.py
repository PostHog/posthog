import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.bitrise import BitriseResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.source import BitriseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BitriseSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestBitriseSource:
    def setup_method(self):
        self.source = BitriseSource()
        self.team_id = 123
        self.config = BitriseSourceConfig(api_token="bitrise-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.BITRISE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Bitrise"
        assert config.label == "Bitrise"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/bitrise.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/bitrise"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.bitrise.io/v0.1/apps",
            "403 Client Error: Forbidden for url: https://api.bitrise.io/v0.1/apps/abc123/builds",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.bitrise.io/v0.1/apps",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only builds (and artifacts, through their parent build fan-out) can be filtered
        # server-side via the `after` Unix-timestamp param.
        assert incremental == {"builds", "artifacts"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["builds"].incremental_fields == INCREMENTAL_FIELDS["builds"]
        assert [f["field"] for f in schemas["builds"].incremental_fields] == ["triggered_at"]
        assert [f["field"] for f in schemas["artifacts"].incremental_fields] == ["build_triggered_at"]
        assert schemas["apps"].incremental_fields == []
        # Builds mutate after creation, so append mode is never offered.
        assert all(schema.supports_append is False for schema in schemas.values())

    def test_artifacts_disabled_by_default(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["artifacts"].should_sync_default is False
        assert schemas["builds"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["builds"])
        assert len(schemas) == 1
        assert schemas[0].name == "builds"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Bitrise API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.source.validate_bitrise_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is BitriseResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.source.bitrise_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_bitrise_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "builds"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_bitrise_source.assert_called_once()
        kwargs = mock_bitrise_source.call_args.kwargs
        assert kwargs["api_token"] == "bitrise-token"
        assert kwargs["endpoint"] == "builds"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-02T03:04:05Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.source.bitrise_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_bitrise_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "builds"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_bitrise_source.call_args.kwargs["db_incremental_field_last_value"] is None
