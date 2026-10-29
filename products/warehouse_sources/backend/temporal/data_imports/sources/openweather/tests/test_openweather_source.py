from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openweather import (
    OpenWeatherSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.settings import (
    API_VERSION_2_5,
    API_VERSION_3_0,
    API_VERSION_4_0,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openweather.source import OpenWeatherSource


class TestOpenWeatherSource:
    def setup_method(self):
        self.source = OpenWeatherSource()
        self.team_id = 123
        self.config = OpenWeatherSourceConfig(api_key="test-key", locations="51.5,-0.12,London")

    def test_default_version_is_4_0(self):
        # New sources are stamped with `default_version`; the 4.0 One Call product is now the default.
        assert self.source.default_version == API_VERSION_4_0
        assert set(self.source.supported_versions) == {API_VERSION_2_5, API_VERSION_3_0, API_VERSION_4_0}

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["forecast"], api_version=API_VERSION_2_5)

        assert [schema.name for schema in schemas] == ["forecast"]

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (
                401,
                False,
                "Invalid OpenWeather API key. Note that a newly created key can take up to a couple of hours to activate.",
            ),
        ],
    )
    def test_validate_credentials(self, status: int, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, "current_weather")

        assert is_valid is expected_valid
        assert error_message == expected_message
        # No pin at validation time (pre-creation) resolves to the default version.
        assert [request.path for request in network.requests_log] == ["/data/4.0/onecall/current"]
        assert network.requests_log[0].param("appid") == self.config.api_key

    @pytest.mark.parametrize(
        "pin, schema_name, expected_version, expected_path",
        [
            (None, "current", API_VERSION_4_0, "/data/4.0/onecall/current"),  # unpinned → default
            (API_VERSION_4_0, "quarter_hourly", API_VERSION_4_0, "/data/4.0/onecall/timeline/15min"),
            (API_VERSION_3_0, "current", API_VERSION_3_0, "/data/3.0/onecall"),  # a 3.0-pinned source keeps its version
            (API_VERSION_2_5, "forecast", API_VERSION_2_5, "/data/2.5/forecast"),
        ],
    )
    def test_source_for_pipeline_plumbs_resolved_version(
        self, pin: str | None, schema_name: str, expected_version: str, expected_path: str
    ) -> None:
        body: dict[str, Any]
        if expected_version == API_VERSION_2_5:
            body = {"list": [{"dt": 1}]}
        elif expected_version == API_VERSION_3_0:
            body = {"current": {"dt": 1}}
        else:
            body = {"data": [{"dt": 1}]}

        result = SourceDriver(self.source, self.config).run(schema_name, [ScriptedResponse(json=body)], api_version=pin)

        assert result.raised is None
        assert result.paths == [expected_path]
        assert result.requests[0].param("appid") == self.config.api_key
        assert result.requests[0].param("lat") == "51.5"
        assert result.requests[0].param("lon") == "-0.12"
        assert result.response is not None
        assert result.response.name == schema_name
        assert result.rows[0]["dt"] == 1
        assert result.rows[0]["location_label"] == "London"
