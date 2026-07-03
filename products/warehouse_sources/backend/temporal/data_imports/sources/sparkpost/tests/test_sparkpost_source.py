from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SparkPostSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import (
    ENDPOINTS,
    LIMITED_RETENTION_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source import SparkPostSource
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.sparkpost import SparkPostResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"events"}


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "events",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestSparkPostSource:
    def setup_method(self) -> None:
        self.source = SparkPostSource()
        self.team_id = 123
        self.config = SparkPostSourceConfig(api_key="sp-key", region="us")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SPARKPOST

    def test_region_is_a_connection_host_field(self) -> None:
        # Changing the region must force the API key to be re-entered so it's never sent to a
        # freshly-specified host.
        assert self.source.connection_host_fields == ["region"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "SparkPost"
        assert config.label == "SparkPost"
        # Shipped hidden for now (not yet exercised against a live account).
        assert config.unreleasedSource is True
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/sparkpost.png"

        region_field, api_key_field = config.fields

        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.name == "region"
        assert region_field.required is True
        assert region_field.defaultValue == "us"
        assert {o.value for o in region_field.options} == {"us", "eu"}

        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        for name in INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert schemas[name].incremental_fields == [
                {
                    "label": "timestamp",
                    "type": "datetime",
                    "field": "timestamp",
                    "field_type": "datetime",
                }
            ]

        for name in set(ENDPOINTS) - INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_retention_description(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        for name in LIMITED_RETENTION_ENDPOINTS:
            assert schemas[name].description is not None
        assert schemas["templates"].description is None

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["templates"])
        assert len(schemas) == 1
        assert schemas[0].name == "templates"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            ((True, None), True, None),
            ((False, "Invalid SparkPost API key."), False, "Invalid SparkPost API key."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source.validate_sparkpost_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, str | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("us", "sp-key")

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SparkPostResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source.sparkpost_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="templates", team_id=99, job_id="job-xyz")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            region="us",
            api_key="sp-key",
            endpoint="templates",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source.sparkpost_source")
    def test_source_for_pipeline_passes_incremental_value_when_enabled(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            schema_name="events",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="timestamp",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.source.sparkpost_source")
    def test_source_for_pipeline_omits_incremental_value_when_disabled(self, mock_source: mock.MagicMock) -> None:
        # When incremental is off the stored watermark must not leak through as a server-side filter.
        inputs = _make_inputs(
            schema_name="events",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
