from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MetaplaneSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.metaplane import MetaplaneResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.source import MetaplaneSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "monitor_evaluations")
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", False)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", None)
    return inputs


class TestMetaplaneSource:
    def setup_method(self) -> None:
        self.source = MetaplaneSource()
        self.team_id = 123
        self.config = MetaplaneSourceConfig(api_key="mp-test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.METAPLANE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Metaplane"
        assert config.label == "Metaplane by Datadog"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is not True
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True

    def test_get_schemas_matches_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_get_schemas_incremental_flags(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        expected_incremental = endpoint == "monitor_evaluations"
        assert schema.supports_incremental is expected_incremental
        # Merge-only everywhere: the evaluation cursor may re-pull the watermark row,
        # which append mode would materialize as a duplicate.
        assert schema.supports_append is False
        if expected_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["createdAt"]
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["monitors"])
        assert [s.name for s in schemas] == ["monitors"]

    @pytest.mark.parametrize("expected_key_prefix", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key_prefix: str) -> None:
        errors = self.source.get_non_retryable_errors()
        assert any(key.startswith(expected_key_prefix) for key in errors)

    @pytest.mark.parametrize(
        "is_valid, expected_valid, expected_has_message",
        [
            (True, True, False),
            (False, False, True),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.source.validate_metaplane_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        is_valid: bool,
        expected_valid: bool,
        expected_has_message: bool,
    ) -> None:
        mock_validate.return_value = is_valid
        valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert valid is expected_valid
        assert (message is not None) is expected_has_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MetaplaneResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.source.metaplane_source")
    def test_source_for_pipeline_passes_arguments(self, mock_metaplane_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            schema_name="monitor_evaluations",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_metaplane_source.call_args
        assert kwargs["api_key"] == self.config.api_key
        assert kwargs["endpoint"] == "monitor_evaluations"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.source.metaplane_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(
        self, mock_metaplane_source: mock.MagicMock
    ) -> None:
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="ignored")
        self.source.source_for_pipeline(self.config, mock.MagicMock(spec=ResumableSourceManager), inputs)

        _, kwargs = mock_metaplane_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
