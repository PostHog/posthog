import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.weightsandbiases import (
    WeightsAndBiasesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.source import (
    WeightsAndBiasesSource,
)


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
        "viewer, expected_valid, expected_message",
        [
            ({"id": "abc"}, True, None),
            (None, False, "Invalid Weights & Biases API key"),
        ],
    )
    def test_validate_credentials(self, viewer, expected_valid, expected_message):
        with scripted_network([ScriptedResponse(json={"data": {"viewer": viewer}})]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert [request.url for request in network.requests_log] == ["https://api.wandb.ai/graphql"]

    def test_validate_credentials_rejects_non_https_host_before_api_call(self):
        config = WeightsAndBiasesSourceConfig(api_key="wb-key", entity="acme", host="http://acme.wandb.io")

        with scripted_network([]) as network:
            is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message is not None and "https" in error_message
        assert network.requests_log == []
