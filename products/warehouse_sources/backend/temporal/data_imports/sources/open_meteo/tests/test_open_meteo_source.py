from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import structlog

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
from products.warehouse_sources.backend.temporal.data_imports.sources.open_meteo.settings import ENDPOINTS
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

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["weather_current", "air_quality_hourly"])

        assert {schema.name for schema in schemas} == {"weather_current", "air_quality_hourly"}

    def test_canonical_descriptions_cover_every_schema(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "raised_message",
        [
            "HTTPSConnectionPool(host='archive-api.open-meteo.com', port=443): "
            "Max retries exceeded with url: /v1/archive?latitude=48.86&longitude=2.35 "
            "(Caused by ReadTimeoutError(\"HTTPSConnectionPool(host='archive-api.open-meteo.com', "
            'port=443): Read timed out. (read timeout=60)"))',
            "HTTPSConnectionPool(host='customer-api.open-meteo.com', port=443): "
            "Max retries exceeded with url: /v1/forecast (Caused by "
            "NewConnectionError('Failed to establish a new connection'))",
            # `_fetch`'s `raise_for_status()` fallback fires once the tracked session's own 429/5xx
            # retries are exhausted; its message carries the request URL rather than urllib3's
            # connection-pool wording.
            "500 Server Error: Internal Server Error for url: https://api.open-meteo.com/v1/forecast",
        ],
    )
    def test_transport_connection_errors_match_the_retryable_patterns(self, raised_message: str) -> None:
        # `_get_with_redacted_errors` has no retry loop of its own once urllib3's own retry budget
        # is exhausted, so a plain read-timeout, connection failure, or exhausted-retry HTTP error
        # against Open-Meteo's own fixed hosts must be recognized here — otherwise it escapes
        # unclassified and gets reported to error tracking as a bug instead of a transient,
        # self-recovering blip.
        assert error_message_matches(raised_message, self.source.get_retryable_errors())

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
