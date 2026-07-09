import pytest
from unittest import mock

from posthog.schema import ExternalDataSourceType as SchemaExternalDataSourceType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.cursor import CursorResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.source import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CursorSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": "usage_events",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": mock.Mock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestCursorSource:
    def setup_method(self):
        self.source = CursorSource()
        self.config = CursorSourceConfig(api_key="key_test")
        self.team_id = 123

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CURSOR

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name == SchemaExternalDataSourceType.CURSOR
        assert config.label == "Cursor"
        assert config.unreleasedSource is True
        assert [f.name for f in config.fields] == ["api_key"]
        assert config.fields[0].required is True
        assert config.fields[0].secret is True
        # The docs slug is derived from docsUrl; a mismatch 404s the public doc.
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cursor"

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [s.name for s in schemas] == ["members", "daily_usage", "usage_events", "spend"]
        assert all(s.should_sync_default for s in schemas)

    @pytest.mark.parametrize(
        "endpoint,supports_incremental,incremental_field",
        [
            ("members", False, None),
            ("daily_usage", True, "date"),
            ("usage_events", True, "timestamp"),
            ("spend", False, None),
        ],
    )
    def test_get_schemas_incremental_support(self, endpoint, supports_incremental, incremental_field):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = schemas[endpoint]

        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        if incremental_field:
            assert [f["field"] for f in schema.incremental_fields] == [incremental_field]
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["members", "spend"])

        assert [s.name for s in schemas] == ["members", "spend"]

    def test_get_documented_tables_lists_endpoints_without_credentials(self):
        # lists_tables_without_credentials=True drives the public docs' Supported tables section.
        tables = self.source.get_documented_tables()

        assert [t["name"] for t in tables] == ["members", "daily_usage", "usage_events", "spend"]
        assert all(t["description"] for t in tables)

    @pytest.mark.parametrize("valid,expected", [(True, (True, None)), (False, (False, "Invalid Cursor Admin API key"))])
    def test_validate_credentials(self, valid, expected):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cursor.source.validate_cursor_credentials",
            return_value=valid,
        ):
            assert self.source.validate_credentials(self.config, self.team_id) == expected

    @pytest.mark.parametrize("status", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors_cover_credential_failures(self, status):
        keys = self.source.get_non_retryable_errors()
        assert any(key.startswith(status) for key in keys)

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert manager._data_class is CursorResumeConfig

    @pytest.mark.parametrize(
        "should_use_incremental_field,last_value,expected_last_value",
        [
            (True, 1700000000000, 1700000000000),
            # A stale watermark must not leak into a full-refresh run.
            (False, 1700000000000, None),
        ],
    )
    def test_source_for_pipeline_plumbs_arguments(self, should_use_incremental_field, last_value, expected_last_value):
        inputs = _make_inputs(
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
        manager = mock.Mock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cursor.source.cursor_source"
        ) as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="key_test",
            endpoint="usage_events",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=expected_last_value,
        )
