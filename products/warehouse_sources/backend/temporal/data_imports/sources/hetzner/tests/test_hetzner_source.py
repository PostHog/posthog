from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import (
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hetzner import (
    HetznerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.source import HetznerSource


class TestHetznerSource:
    def setup_method(self) -> None:
        self.source = HetznerSource()
        self.team_id = 1

    def test_config_has_single_secret_token_field(self) -> None:
        # The token is a credential — it must render as a masked password input and be marked secret,
        # or it would be stored/echoed in plaintext.
        config = self.source.get_source_config
        assert config.releaseStatus == ReleaseStatus.GA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/hetzner"
        fields = config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_token"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    @parameterized.expand(
        [
            ("list", "servers", ["id"]),
            ("server_metrics", "server_metrics", ["server_id", "metric", "timestamp"]),
            ("load_balancer_metrics", "load_balancer_metrics", ["load_balancer_id", "metric", "timestamp"]),
            ("network_members", "network_members", ["network_id", "type", "id"]),
        ]
    )
    def test_source_for_pipeline_routes_schema(self, _name: str, schema_name: str, primary_keys: list[str]) -> None:
        config = HetznerSourceConfig(api_token="tok")
        result = SourceDriver(self.source, config).run(schema_name, [ScriptedResponse(json={})])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == schema_name
        assert response.primary_keys == primary_keys
