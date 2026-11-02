from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.oncehub import (
    OncehubSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.source import OncehubSource


class TestOncehubSource:
    def setup_method(self) -> None:
        self.source = OncehubSource()
        self.team_id = 123
        self.config = OncehubSourceConfig(api_key="oncehub-key")

    def test_validate_credentials_delegates_with_api_key(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]) as network:
            result = self.source.validate_credentials(self.config, self.team_id)

        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["api-key"] == "oncehub-key"
        assert result == (False, "Invalid OnceHub API key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.source.oncehub_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bookings"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "oncehub-key"
        assert kwargs["endpoint"] == "bookings"
        assert kwargs["resumable_source_manager"] is manager
