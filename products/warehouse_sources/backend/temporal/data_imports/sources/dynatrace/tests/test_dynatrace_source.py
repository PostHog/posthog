from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.source import DynatraceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynatrace import (
    DynatraceSourceConfig,
)


class TestDynatraceSource:
    def setup_method(self) -> None:
        self.source = DynatraceSource()
        self.team_id = 123
        self.config = DynatraceSourceConfig(
            environment_url="https://abc12345.live.dynatrace.com", api_token="dt0c01.token"
        )

    def test_environment_url_is_a_connection_host_field(self) -> None:
        # Changing the environment URL must force the token to be re-entered so it's never
        # sent to a freshly-specified host.
        assert self.source.connection_host_fields == ["environment_url"]
