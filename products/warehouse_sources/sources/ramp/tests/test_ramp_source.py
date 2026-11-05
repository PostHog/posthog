import pytest

from products.warehouse_sources.sources.ramp._config import RampSourceConfig
from products.warehouse_sources.sources.ramp.source import RampSource


class TestRampSource:
    def setup_method(self):
        self.source = RampSource()
        self.team_id = 123
        self.config = RampSourceConfig(environment="production", client_id="cid", client_secret="sec")

    def test_environment_is_a_connection_host_field(self):
        # Changing environment retargets where the stored client secret is sent, so it must force
        # re-entering secrets.
        assert self.source.connection_host_fields == ["environment"]

    @pytest.mark.parametrize(
        "endpoint, expected_lookback_seconds",
        [
            ("transfers", 7 * 24 * 60 * 60),
            ("statements", None),
            ("transactions", None),
        ],
    )
    def test_incremental_lookback_default_reaches_the_schema(self, endpoint, expected_lookback_seconds):
        [schema] = self.source.get_schemas(self.config, self.team_id, names=[endpoint])

        assert schema.default_incremental_lookback_seconds == expected_lookback_seconds
