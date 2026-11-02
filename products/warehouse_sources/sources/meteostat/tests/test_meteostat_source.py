from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.meteostat import (
    MeteostatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.settings import (
    MAX_STATIONS,
    POINT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.source import MeteostatSource


class TestMeteostatSource:
    def setup_method(self):
        self.source = MeteostatSource()
        self.team_id = 123
        self.config = MeteostatSourceConfig(api_key="key-123", station_ids="10637")

    def test_validate_credentials_rejects_no_stations(self):
        config = MeteostatSourceConfig(api_key="key-123", station_ids="")
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and "station" in message.lower()

    def test_validate_credentials_rejects_too_many_stations(self):
        station_ids = ",".join(str(i) for i in range(MAX_STATIONS + 1))
        config = MeteostatSourceConfig(api_key="key-123", station_ids=station_ids)
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and str(MAX_STATIONS) in message

    def test_validate_credentials_rejects_start_date_before_floor(self):
        config = MeteostatSourceConfig(api_key="key-123", station_ids="10637", start_date="0001-01-01")
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and "start date" in message.lower()

    def test_validate_credentials_rejects_invalid_locations(self):
        config = MeteostatSourceConfig(api_key="key-123", station_ids="10637", locations="43.6,-79.4;north,west")

        with scripted_network([]) as network:
            is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message is not None and "north,west" in message
        assert network.requests_log == []

    @parameterized.expand(
        [
            ("no_locations", None, False),
            ("blank_locations", "  ", False),
            ("with_locations", "43.6667,-79.4", True),
        ]
    )
    def test_point_tables_are_selected_by_default_only_with_locations(self, _name, locations, expected):
        config = MeteostatSourceConfig(api_key="key-123", station_ids="10637", locations=locations)

        defaults = {schema.name: schema.should_sync_default for schema in self.source.get_schemas(config, self.team_id)}

        assert {name for name, selected in defaults.items() if not selected} == (
            set() if expected else set(POINT_ENDPOINTS)
        )

    def test_validate_credentials_probes_the_first_configured_station(self):
        config = MeteostatSourceConfig(api_key="key-123", station_ids="10637, 71508")

        with scripted_network([ScriptedResponse(status=200)]) as network:
            is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is True
        assert message is None
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/stations/meta"
        assert network.requests_log[0].param("id") == "10637"
        assert network.requests_log[0].headers["x-rapidapi-key"] == "key-123"
