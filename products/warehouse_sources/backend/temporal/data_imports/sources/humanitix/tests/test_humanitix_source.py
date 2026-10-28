from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.humanitix import (
    HumanitixSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.source import HumanitixSource


class TestHumanitixSource:
    def setup_method(self) -> None:
        self.source = HumanitixSource()
        self.team_id = 123
        self.config = HumanitixSourceConfig(api_key="hmtx-key")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_validate_credentials_probes_the_account_key(self) -> None:
        # The API key is account-wide, so validation probes the key, not a per-schema scope.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert self.source.validate_credentials(self.config, self.team_id, schema_name="tags") == (True, None)

        assert [request.path for request in network.requests_log] == ["/v1/events"]
        assert network.requests_log[0].headers["x-api-key"] == "hmtx-key"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.source.humanitix_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_humanitix_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_humanitix_source.assert_called_once()
        kwargs = mock_humanitix_source.call_args.kwargs
        assert kwargs["api_key"] == "hmtx-key"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager
