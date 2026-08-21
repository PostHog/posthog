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

    def test_get_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only runs has a verified server-side timestamp filter; everything else is full refresh.
        assert [name for name, schema in schemas.items() if schema.supports_incremental] == ["runs"]
        # Runs mutate after creation, so merge is the only safe write mode.
        assert not any(schema.supports_append for schema in schemas.values())
        assert [f["field"] for f in schemas["runs"].incremental_fields] == ["createdAt", "heartbeatAt"]
        assert schemas["runs"].incremental_fields == INCREMENTAL_FIELDS["runs"]

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
