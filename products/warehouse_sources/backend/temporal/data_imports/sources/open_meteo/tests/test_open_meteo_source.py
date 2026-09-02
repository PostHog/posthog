from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openmeteo import (
    OpenMeteoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.open_meteo import OpenMeteoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.settings import (
    ARCHIVE_LOOKBACK_SECONDS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.source import OpenMeteoSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.source"


def _inputs(
    schema_name: str = "weather_archive_hourly",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="time_utc",
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestOpenMeteoSource:
    def setup_method(self) -> None:
        self.source = OpenMeteoSource()
        self.team_id = 123
        self.config = OpenMeteoSourceConfig(locations="51.5,-0.12,London", start_date="2024-01-01", api_key=None)

    def test_source_config_is_released_as_alpha(self) -> None:
        config = self.source.get_source_config

        # `unreleasedSource` hides the connector from users entirely, so a finished source must not set it.
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.name.value == "OpenMeteo"
        assert config.label == "Open-Meteo"
        assert config.iconPath == "/static/services/open_meteo.png"

    def test_source_config_fields(self) -> None:
        fields = self.source.get_source_config.fields
        by_name = {field.name: field for field in fields if isinstance(field, SourceFieldInputConfig)}

        assert set(by_name) == {"locations", "start_date", "api_key"}
        assert by_name["locations"].type == SourceFieldInputConfigType.TEXTAREA
        assert by_name["locations"].required is True
        # Open-Meteo's core API is keyless, so a commercial key must stay optional.
        assert by_name["api_key"].required is False
        assert by_name["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert by_name["api_key"].secret is True
        assert by_name["start_date"].required is False
        assert by_name["start_date"].secret is False

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        assert all(schema.detected_primary_keys == ["location_id", "time_utc"] for schema in schemas)

    @pytest.mark.parametrize(
        "schema_name,supports_incremental,supports_append,lookback",
        [
            ("weather_archive_hourly", True, True, ARCHIVE_LOOKBACK_SECONDS),
            ("weather_archive_daily", True, True, ARCHIVE_LOOKBACK_SECONDS),
            # Forecast values for a given timestamp are revised on every model run and the newest
            # timestamp is in the future, so neither a merge watermark nor an append cursor works.
            ("weather_forecast_hourly", False, False, None),
            ("weather_forecast_daily", False, False, None),
            ("air_quality_hourly", False, False, None),
            # No server-side timestamp filter exists for current conditions, so append only.
            ("weather_current", False, True, None),
        ],
    )
    def test_sync_capabilities_per_schema(
        self, schema_name: str, supports_incremental: bool, supports_append: bool, lookback: int | None
    ) -> None:
        schema = self.source.get_schemas(self.config, self.team_id, names=[schema_name])[0]

        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_append
        assert schema.default_incremental_lookback_seconds == lookback
        assert bool(schema.incremental_fields) is (supports_incremental or supports_append)

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["weather_current", "air_quality_hourly"])

        assert {schema.name for schema in schemas} == {"weather_current", "air_quality_hourly"}

    def test_documented_tables_are_listed_without_credentials(self) -> None:
        tables = self.source.get_documented_tables()

        assert [table["name"] for table in tables] == list(ENDPOINTS)
        assert all(table["description"] for table in tables)

    def test_canonical_descriptions_cover_every_schema(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "raised_message",
        [
            "Open-Meteo rejected the API key (status 401): Invalid API key",
            "Open-Meteo rejected the request (status 400): Latitude must be in range of -90 to 90",
        ],
    )
    def test_transport_errors_match_the_non_retryable_patterns(self, raised_message: str) -> None:
        # The transport builds these strings; a reworded message there would silently make the source
        # retry a permanent failure forever.
        assert error_message_matches(raised_message, self.source.get_non_retryable_errors().keys())

    def test_resumable_manager_is_namespaced_per_schema(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs("weather_current"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OpenMeteoResumeConfig
        # The archive stores a date and the rolling endpoints a location index. Sharing one Redis key
        # would let a retry that switches schema load a cursor the other endpoint cannot use.
        assert manager._namespace == "weather_current"

    def test_source_for_pipeline_returns_a_lazy_response(self) -> None:
        response = self.source.source_for_pipeline(self.config, mock.MagicMock(), _inputs("weather_current"))

        assert response.name == "weather_current"
        assert response.primary_keys == ["location_id", "time_utc"]
        # Building the response must not reach the API; only iterating it does.
        assert callable(response.items)
        assert isinstance(cast("Iterable[Any]", response.items()), Iterable)
