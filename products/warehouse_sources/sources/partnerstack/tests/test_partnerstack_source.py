from unittest import mock

from products.warehouse_sources.sources.partnerstack._config import PartnerStackSourceConfig
from products.warehouse_sources.sources.partnerstack.source import PartnerStackSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


class TestPartnerStackSource:
    def setup_method(self) -> None:
        self.source = PartnerStackSource()
        self.team_id = 123
        self.config = PartnerStackSourceConfig(public_key="pub", private_key="priv")

    def test_validate_credentials_delegates(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]) as network:
            result = self.source.validate_credentials(self.config, self.team_id)

        assert result == (False, "Invalid PartnerStack API keys")
        assert network.requests_log[0].headers["authorization"] == "Basic cHViOnByaXY="

    @mock.patch("products.warehouse_sources.sources.partnerstack.source.partnerstack_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "partnerships"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["public_key"] == "pub"
        assert kwargs["private_key"] == "priv"
        assert kwargs["endpoint"] == "partnerships"
        assert kwargs["resumable_source_manager"] is manager
