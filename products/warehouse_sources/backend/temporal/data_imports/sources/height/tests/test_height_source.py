from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.height import HeightSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.height.source import HeightSource


class TestHeightSource:
    def setup_method(self) -> None:
        self.source = HeightSource()
        self.team_id = 123
        self.config = HeightSourceConfig(api_key="secret_key")

    def test_validate_credentials_delegates_to_height(self) -> None:
        # The status/message mapping is owned by height.validate_credentials (covered in test_height.py);
        # here we assert the source sends the configured API key and returns the result.
        with scripted_network([ScriptedResponse(status=401)]) as network:
            result = self.source.validate_credentials(self.config, self.team_id)

        assert [request.path for request in network.requests_log] == ["/users"]
        assert network.requests_log[0].headers["authorization"] == "api-key secret_key"
        assert result == (False, "Invalid Height API key")

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        result = SourceDriver(self.source, self.config).run("users", [ScriptedResponse(json={"list": []})])

        assert result.raised is None
        assert result.paths == ["/users"]
        assert result.requests[0].headers["authorization"] == "api-key secret_key"
