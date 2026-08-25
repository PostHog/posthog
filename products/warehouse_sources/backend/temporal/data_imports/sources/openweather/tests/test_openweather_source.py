import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
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


def _make_inputs(schema_name: str = "current_weather", api_version: str | None = None) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
        api_version=api_version,
    )


class TestOpenWeatherSource:
    def setup_method(self):
        self.source = OpenWeatherSource()
        self.team_id = 123
        self.config = OpenWeatherSourceConfig(api_key="test-key", locations="51.5,-0.12,London")

    def test_default_version_is_3_0(self):
        # New sources are stamped with `default_version`; the 3.0 One Call product is now the default.
        assert self.source.default_version == API_VERSION_3_0
        assert set(self.source.supported_versions) == {API_VERSION_2_5, API_VERSION_3_0}

    @pytest.mark.parametrize(
        "api_version, expected",
        [
            (None, {"current", "hourly", "daily"}),  # None → default_version (3.0)
            (API_VERSION_3_0, {"current", "hourly", "daily"}),
            (API_VERSION_2_5, {"current_weather", "forecast", "air_pollution", "air_pollution_forecast"}),
        ],
    )
    def test_get_schemas_lists_the_versions_endpoints(self, api_version, expected):
        schemas = self.source.get_schemas(self.config, self.team_id, api_version=api_version)

        assert {schema.name for schema in schemas} == expected

    @pytest.mark.parametrize("api_version, endpoint", _ALL_VERSIONED_ENDPOINTS)
    def test_get_schemas_supports_append_not_incremental(self, api_version, endpoint):
        # No endpoint exposes a server-side timestamp filter, so none is truly incremental;
        # all support append so users can accumulate snapshots over time.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id, api_version=api_version)}

        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is True
        assert [f["field"] for f in schemas[endpoint].incremental_fields] == ["dt"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["forecast"], api_version=API_VERSION_2_5)

        assert [schema.name for schema in schemas] == ["forecast"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid OpenWeather API key"), False, "Invalid OpenWeather API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.openweather.source.validate_openweather_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, "current_weather")

        assert is_valid is expected_valid
        assert error_message == expected_message
        # No pin at validation time (pre-creation) resolves to the default version.
        mock_validate.assert_called_once_with(self.config.api_key, self.config.locations, API_VERSION_3_0)

    @pytest.mark.parametrize(
        "pin, schema_name, expected_version",
        [
            (None, "current", API_VERSION_3_0),  # unpinned → default
            (API_VERSION_3_0, "current", API_VERSION_3_0),
            (API_VERSION_2_5, "forecast", API_VERSION_2_5),  # a 2.5-pinned source keeps its version
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.openweather.source.openweather_source"
    )
    def test_source_for_pipeline_plumbs_resolved_version(
        self, mock_openweather_source, pin, schema_name, expected_version
    ):
        inputs = _make_inputs(schema_name=schema_name, api_version=pin)

        self.source.source_for_pipeline(self.config, inputs)

        mock_openweather_source.assert_called_once_with(
            api_key="test-key",
            endpoint=schema_name,
            locations_raw="51.5,-0.12,London",
            logger=inputs.logger,
            api_version=expected_version,
        )
