import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    WeightsAndBiasesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.source import (
    WeightsAndBiasesSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.weights_and_biases import (
    WeightsAndBiasesResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.source"


class TestWeightsAndBiasesSource:
    def setup_method(self):
        self.source = WeightsAndBiasesSource()
        self.team_id = 123
        self.config = WeightsAndBiasesSourceConfig(api_key="wb-key", entity="acme")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.WEIGHTSANDBIASES

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "WeightsAndBiases"
        assert config.label == "Weights & Biases"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert [f.name for f in config.fields] == ["api_key", "entity", "host"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    def test_host_field_is_optional(self):
        config = self.source.get_source_config
        host_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "host")
        assert host_field.required is False

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.wandb.ai/graphql",
            "401 Client Error: Unauthorized for url: https://acme.wandb.io/graphql",
            "Weights & Biases GraphQL error: permission denied",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://api.wandb.ai/graphql",
            "Weights & Biases GraphQL error: something went wrong",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient_failures(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only runs has a verified server-side timestamp filter; everything else is full refresh.
        assert [name for name, schema in schemas.items() if schema.supports_incremental] == ["runs"]
        # Runs mutate after creation, so merge is the only safe write mode.
        assert not any(schema.supports_append for schema in schemas.values())
        assert [f["field"] for f in schemas["runs"].incremental_fields] == ["createdAt", "heartbeatAt"]
        assert schemas["runs"].incremental_fields == INCREMENTAL_FIELDS["runs"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["runs", "nope"])
        assert [schema.name for schema in schemas] == ["runs"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Weights & Biases API key"),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_wandb_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("wb-key", None)

    @mock.patch(f"{_SOURCE_MODULE}.validate_wandb_credentials")
    def test_validate_credentials_rejects_non_https_host_before_api_call(self, mock_validate):
        config = WeightsAndBiasesSourceConfig(api_key="wb-key", entity="acme", host="http://acme.wandb.io")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message is not None and "https" in error_message
        mock_validate.assert_not_called()

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WeightsAndBiasesResumeConfig

    @mock.patch(f"{_SOURCE_MODULE}.weights_and_biases_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_wandb_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "runs"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        inputs.incremental_field = "heartbeatAt"
        manager = mock.MagicMock()
        config = WeightsAndBiasesSourceConfig(api_key="wb-key", entity="acme", host="https://acme.wandb.io")

        self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_wandb_source.call_args.kwargs
        assert kwargs["api_key"] == "wb-key"
        assert kwargs["entity"] == "acme"
        assert kwargs["host"] == "https://acme.wandb.io"
        assert kwargs["endpoint"] == "runs"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"
        assert kwargs["incremental_field"] == "heartbeatAt"

    @mock.patch(f"{_SOURCE_MODULE}.weights_and_biases_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_wandb_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_wandb_source.call_args.kwargs["db_incremental_field_last_value"] is None
