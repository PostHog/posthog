from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.meteostat import (
    MeteostatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.settings import MAX_STATIONS
from products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.source import MeteostatSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.meteostat.source"


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

    @mock.patch(f"{MODULE}.validate_station")
    def test_validate_credentials_probes_the_first_configured_station(self, mock_validate):
        mock_validate.return_value = (True, None)
        config = MeteostatSourceConfig(api_key="key-123", station_ids="10637, 71508")

        is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is True
        assert message is None
        mock_validate.assert_called_once_with("key-123", "10637")
