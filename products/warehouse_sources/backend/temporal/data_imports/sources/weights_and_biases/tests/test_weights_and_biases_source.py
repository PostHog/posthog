import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.weightsandbiases import (
    WeightsAndBiasesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.source import (
    WeightsAndBiasesSource,
)

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.source"


class TestWeightsAndBiasesSource:
    def setup_method(self):
        self.source = WeightsAndBiasesSource()
        self.team_id = 123
        self.config = WeightsAndBiasesSourceConfig(api_key="wb-key", entity="acme")

    def test_entity_is_a_connection_host_field(self):
        # Changing `entity` retargets the stored key at another W&B account's data, so the update
        # serializer must re-require the key — guard against dropping that from the override.
        assert "entity" in self.source.connection_host_fields

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
