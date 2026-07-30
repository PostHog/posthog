from typing import Any, cast

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack import AppstackResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.settings import (
    DEFAULT_INCREMENTAL_LOOKBACK_SECONDS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.source import AppstackSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appstack import (
    AppstackSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> AppstackSourceConfig:
    return AppstackSourceConfig(api_key="appstack-key")


class TestAppstackSourceConfig:
    def test_source_type(self) -> None:
        assert AppstackSource().source_type == ExternalDataSourceType.APPSTACK

    def test_get_source_config(self) -> None:
        config = AppstackSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.APPSTACK
        assert config.category == DataWarehouseSourceCategory.ADVERTISING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source ships visible: the scaffold's unreleasedSource flag must stay deleted.
        assert not config.unreleasedSource

    def test_single_secret_api_key_field(self) -> None:
        fields = AppstackSource().get_source_config.fields
        assert fields is not None
        assert len(fields) == 1
        api_key_field = fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True


class TestGetSchemas:
    def test_events_schema(self) -> None:
        schemas = AppstackSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

        events = next(s for s in schemas if s.name == "events")
        assert events.supports_incremental is True
        # The lookback re-reads a trailing window each run; append would duplicate the overlap.
        assert events.supports_append is False
        assert [f["field"] for f in events.incremental_fields] == ["event_time"]
        assert events.default_incremental_lookback_seconds == DEFAULT_INCREMENTAL_LOOKBACK_SECONDS

    def test_names_filter(self) -> None:
        assert AppstackSource().get_schemas(_config(), team_id=1, names=["nonexistent"]) == []


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appstack.source.validate_appstack_credentials"
    )
    def test_validate(self, _label: str, api_result: bool, expected_ok: bool, mock_validate: MagicMock) -> None:
        mock_validate.return_value = api_result
        ok, error = AppstackSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appstack.source.validate_appstack_credentials"
    )
    def test_network_blip_is_not_reported_as_bad_credentials(self, mock_validate: MagicMock) -> None:
        mock_validate.side_effect = requests.ConnectionError("boom")
        ok, error = AppstackSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None
        assert "try again" in error


class TestSourceWiring:
    def test_non_retryable_errors_cover_auth(self) -> None:
        errors = AppstackSource().get_non_retryable_errors()
        keys = " ".join(errors.keys())
        assert "401" in keys
        assert "403" in keys

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = AppstackSource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AppstackResumeConfig

    def test_canonical_descriptions_match_endpoints(self) -> None:
        descriptions = AppstackSource().get_canonical_descriptions()
        assert "events" in descriptions
        assert set(descriptions.keys()).issubset(set(ENDPOINTS))

    def test_documented_tables_render_without_credentials(self) -> None:
        # `lists_tables_without_credentials` powers the public docs' Supported tables section.
        tables = AppstackSource().get_documented_tables()
        assert [t["name"] for t in tables] == ["events"]
        assert tables[0]["description"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.appstack.source.appstack_source")
    def test_source_for_pipeline_plumbing(self, mock_appstack_source: MagicMock) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "events"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"

        AppstackSource().source_for_pipeline(_config(), manager, inputs)

        kwargs = cast(dict[str, Any], mock_appstack_source.call_args.kwargs)
        assert kwargs["api_key"] == "appstack-key"
        assert kwargs["endpoint"] == "events"
        assert kwargs["team_id"] == 7
        assert kwargs["job_id"] == "job-1"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00+00:00"
        assert kwargs["resumable_source_manager"] is manager

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.appstack.source.appstack_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_appstack_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "events"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"

        AppstackSource().source_for_pipeline(_config(), MagicMock(spec=ResumableSourceManager), inputs)

        assert mock_appstack_source.call_args.kwargs["db_incremental_field_last_value"] is None
