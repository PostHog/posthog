from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openweather import (
    OpenWeatherSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.settings import (
    API_VERSION_2_5,
    API_VERSION_3_0,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.source import OpenWeatherSource

_ALL_VERSIONED_ENDPOINTS = [
    (version, endpoint) for version in (API_VERSION_2_5, API_VERSION_3_0) for endpoint in endpoints_for_version(version)
]


class TestOpenWeatherSource:
    def setup_method(self):
        self.source = OpenWeatherSource()
        self.team_id = 123
        self.config = OpenWeatherSourceConfig(api_key="test-key", locations="51.5,-0.12,London")

    def test_default_version_is_3_0(self):
        # New sources are stamped with `default_version`; the 3.0 One Call product is now the default.
        assert self.source.default_version == API_VERSION_3_0
        assert set(self.source.supported_versions) == {API_VERSION_2_5, API_VERSION_3_0}
