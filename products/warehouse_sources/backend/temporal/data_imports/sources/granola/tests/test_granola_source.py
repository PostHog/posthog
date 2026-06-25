from datetime import UTC, datetime
from typing import Optional

import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GranolaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.granola.granola import GranolaResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.granola.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.granola.source import GranolaSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(
    schema_name: str = "notes",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: object = None,
    incremental_field: Optional[str] = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field=incremental_field,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestGranolaSource:
    def setup_method(self):
        self.source = GranolaSource()
        self.team_id = 123
        self.config = GranolaSourceConfig(api_key="grn_test")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GRANOLA

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Granola"
        assert config.label == "Granola"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/granola.png"
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, expect_incremental",
        [
            ("notes", True),
            ("folders", False),
        ],
    )
    def test_get_schemas_incremental_support(self, endpoint, expect_incremental):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is expect_incremental
        assert schemas[endpoint].supports_append is expect_incremental

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["notes"])

        assert len(schemas) == 1
        assert schemas[0].name == "notes"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized",
            "403 Client Error: Forbidden",
        ],
    )
    def test_non_retryable_errors_includes_auth_keys(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid Granola API key"), False, "Invalid Granola API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.granola.source.validate_granola_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, "notes")

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, "notes")

    def test_get_resumable_source_manager(self):
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GranolaResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.granola.source.granola_source")
    def test_source_for_pipeline_plumbs_incremental_args(self, mock_granola_source):
        manager = mock.MagicMock()
        last_value = datetime(2026, 1, 1, tzinfo=UTC)
        inputs = _make_inputs(
            schema_name="notes",
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
            incremental_field="updated_at",
        )

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_granola_source.assert_called_once_with(
            api_key="grn_test",
            endpoint="notes",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
            incremental_field="updated_at",
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.granola.source.granola_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_granola_source):
        manager = mock.MagicMock()
        inputs = _make_inputs(
            schema_name="folders",
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_granola_source.call_args
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
